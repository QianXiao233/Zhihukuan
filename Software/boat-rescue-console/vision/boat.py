"""
船体检测：ArUco 码 -> 全局坐标 + 航向

⚠️ 角点顺序：**绝对不要按图像坐标重新排序**。
  cv2.aruco.detectMarkers 返回的四个角点是相对"码本身"固定顺序的
  （tl/tr/br/bl，随码一起旋转），这也是 estimatePoseSingleMarkers 能直接
  复用同一组 object points 的原因。曾经这里用 x+y / y-x 重排，等价于假设
  "码在画面里基本是正的"：码转过 45° 后四个角的物理身份就会认错，航向在
  3/4 的朝向上跳 90°/180°（数值复现见 test_boat_heading.py），表现为船在
  目标附近绕圈、永远进不了 40 cm 末端区。本模块现在直接使用检测器给的原始顺序。

航向精度：9cm 的码在 1080P 俯拍下约百来像素（5cm 时只有几十像素），角点抖动 1~2 px 就会带来
  数度误差，所以方向向量取两条边中点之差（等效平均两条边）、并做低通滤波。
  要进一步提高精度，优先把码印大（10 cm），而不是加大滤波。

ArUco 方向约定：
  原始角点顺序为 码自身坐标系的 tl/tr/br/bl。船头取 码的 -X 方向
  （即 左边中点 - 右边中点）。若实测船头与码的贴法差了 90°/180°，
  改下面的 HEADING_OFFSET_DEG 即可（单位：度，顺时针为正），不必改逻辑。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

from pool import pixel_to_pool

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

MARKER_ID = 0
MARKER_SIZE_M = 0.09          # 9cm x 9cm（与打印一致；仅记录用途，航向/坐标计算不依赖）

# 若实测船头方向与"码左侧边"不一致，用这个偏移校正（单位：度，顺时针为正）
HEADING_OFFSET_DEG = 0.0

# 航向低通滤波系数：0 表示完全不更新，1 表示完全不滤波
# 小码噪声大，适当滤波（0.3~0.5）能明显抑制 PID 振荡
HEADING_SMOOTHING = 0.4


@dataclass
class BoatPose:
    x: float                  # 水池 X（米）
    y: float                  # 水池 Y（米）
    heading: float            # 0-360，0 指向 +Y，顺时针为正
    corner_count: int


def canonical_corners(corners: np.ndarray) -> np.ndarray:
    """
    直接取检测器返回的角点顺序（相对码固定、随码旋转）。

    :param corners: detectMarkers 的单个元素，形状 (1,4,2) 或 (4,2)
    :return: (4,2) float32，顺序为码自身的 tl/tr/br/bl
    """
    return np.asarray(corners, dtype=np.float32).reshape(4, 2)


def heading_from_corners(quad: np.ndarray, H) -> float:
    """
    四个角点（码自身顺序 tl,tr,br,bl）-> 船头航向（0°=+Y，顺时针为正）。

    方向向量取"上边中点 - 下边中点"：打印的码上标了「这一边朝船头」，
    所以码的上边朝向就是船头。

    历史坑：早先这里用的是 `左边中点 - 右边中点`，那算出来的是**垂直于船头**
    的方向，航向会整体偏 90°。表现就是船一直往侧边开、撞池壁，而 PID 却以为
    自己方向是对的（误差还很大，就一直转）。

    两点作差不受平移影响，等于取该点的局部雅可比方向，对透视畸变不敏感。
    """
    top_mid = (quad[0] + quad[1]) / 2.0        # tl,tr 中点 = 上边中点（朝船头）
    bottom_mid = (quad[2] + quad[3]) / 2.0     # br,bl 中点 = 下边中点（朝船尾）
    center_px = quad.mean(axis=0)
    v_px = top_mid - bottom_mid

    a = pixel_to_pool(H, center_px)
    b = pixel_to_pool(H, center_px + v_px)
    dx, dy = b[0] - a[0], b[1] - a[1]

    heading = math.degrees(math.atan2(dx, dy)) % 360.0
    return (heading + HEADING_OFFSET_DEG) % 360.0


class BoatDetector:
    def __init__(self, marker_id: int = MARKER_ID, keep_ms: float = 350.0):
        if not HAS_CV2:
            raise RuntimeError("BoatDetector 需要 OpenCV，请先安装: pip install opencv-python")
        self.marker_id = marker_id
        self.keep_ms = float(keep_ms)
        self._dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self._params = cv2.aruco.DetectorParameters()

        # ---- 放宽检测门槛（现场实测：默认参数在斜角/反光/小码下大量丢检）----
        # 1) 自适应阈值窗口：范围更宽，暗部/高光区域也能分出黑白边界
        self._params.adaptiveThreshWinSizeMin = 3
        self._params.adaptiveThreshWinSizeMax = 45
        self._params.adaptiveThreshWinSizeStep = 4
        self._params.adaptiveThreshConstant = 5.0
        # 2) 码最小/最大周长：允许更小的码（远角）和更大的码（近处贴满）
        self._params.minMarkerPerimeterRate = 0.008
        self._params.maxMarkerPerimeterRate = 4.0
        # 3) 角点精化：亚像素级，斜角下角点更准（航向/位置更稳）
        self._params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self._params.cornerRefinementWinSize = 5
        self._params.cornerRefinementMaxIterations = 30
        self._params.cornerRefinementMinAccuracy = 0.05
        # 4) 允许更明显的透视变形与边长差（斜着看时四边长度差异大）
        self._params.perspectiveRemovePixelPerCell = 8
        self._params.perspectiveRemoveIgnoredMarginPerCell = 0.2
        self._params.maxErroneousBitsInBorderRate = 0.5
        self._params.errorCorrectionRate = 0.8
        # 5) 允许"近似正方形"的轮廓略微不算正方形（透视下会被判成不方）
        self._params.minCornerDistanceRate = 0.02
        self._params.minDistanceToBorder = 2
        self._params.minMarkerDistanceRate = 0.02
        # 6) 二值化方式：自适应阈值在反光下比全局更稳
        self._params.adaptiveThreshWinSizeMax = max(self._params.adaptiveThreshWinSizeMax, 45)

        # OpenCV 4.7+ 用 ArucoDetector；旧版用 detectMarkers
        if hasattr(cv2.aruco, "ArucoDetector"):
            self._detector = cv2.aruco.ArucoDetector(self._dict, self._params)
        else:
            self._detector = None

        self._heading: float | None = None
        self._pool_polygon = None          # 池子轮廓（米），由 set_pool_polygon 注入

        # --- 丢帧延续（水膜/反光导致码间歇性不可见时用）---
        # 实测：码被水打湿后每几帧就丢一次，而 locator 一丢就 reset_filter()，
        # 航向滤波被清零、服务端 400 ms 超时又把船停下 —— 表现为船"抖一下走一下"。
        # 这里在 keep_ms 内沿用上一次位姿（按最后速度外推），超过才真正判丢。
        self._last_pos: tuple[float, float] | None = None      # 最后一次有效位置（米）
        self._last_pos_t: float | None = None                  # 对应时间（秒）
        self._last_vel: tuple[float, float] = (0.0, 0.0)        # 位置变化速度（米/秒）
        self._last_heading: float | None = None

    def _prepare_gray(self, patch):
        """灰度化 + 轻微增强，对抗水膜/反光造成的低对比度。

        码被水打湿后：整体对比度下降、边缘发糊、局部有高光。这里做三件事：
          1) CLAHE 自适应直方图均衡 —— 拉回局部对比度（对高光/暗区都有效）；
          2) 轻度锐化 —— 补一点被水膜糊掉的边缘；
          3) 不做二值化：ArUco 内部会自己算自适应阈值，二值化反而会丢细节。
        开销约 1~2 ms（只在 ROI 上做），相比提升的检出率非常划算。
        """
        if patch.ndim == 3:
            gray = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
        else:
            gray = patch

        # CLAHE：clipLimit 太大容易放大噪点，2.0 是实测比较稳的值
        try:
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            gray = clahe.apply(gray)
        except Exception:
            pass

        # 轻度锐化（3x3 拉普拉斯核的温和版本）
        try:
            blur = cv2.GaussianBlur(gray, (0, 0), 1.0)
            gray = cv2.addWeighted(gray, 1.5, blur, -0.5, 0)
        except Exception:
            pass
        return gray

    def set_pool_polygon(self, polygon_m) -> None:
        """注入水池轮廓（米坐标），供 ROI 搜索用。None 则按 0~1.5 m 粗算。"""
        if polygon_m is None:
            self._pool_polygon = None
            return
        try:
            arr = np.asarray(polygon_m, dtype=np.float64).reshape(-1, 2)
        except Exception:
            self._pool_polygon = None
            return
        self._pool_polygon = arr if len(arr) >= 3 else None

    def _search_roi(self, frame_shape, H):
        """由单应矩阵反推水池在画面里的外接框，作为 ArUco 搜索区域。

        全图 1080P 上跑 detectMarkers 约 31 ms，是主循环最大的单项开销；
        船位只可能在池子里，把搜索范围缩到池子外接框能把耗时降到 1/3 左右。
        返回 (x0, y0, x1, y1) 或 None（无法推算时用全图）。
        """
        if H is None:
            return None
        try:
            H_inv = np.linalg.inv(np.asarray(H, dtype=np.float64))
        except np.linalg.LinAlgError:
            return None
        # 优先用真实池子轮廓（更小的搜索框）；没有轮廓时按 0~1.5 m 粗算
        if getattr(self, "_pool_polygon", None) is not None:
            source = self._pool_polygon
        else:
            source = np.array([(0.0, 0.0), (1.5, 0.0), (1.5, 1.5), (0.0, 1.5)])
        pts = []
        for X, Y in source:
            v = H_inv @ np.array([float(X), float(Y), 1.0])
            if abs(v[2]) < 1e-12:
                return None
            pts.append((v[0] / v[2], v[1] / v[2]))
        pts = np.array(pts, dtype=np.float64)
        h, w = frame_shape[:2]
        pad = 40
        x0 = int(max(0, np.floor(pts[:, 0].min()) - pad))
        y0 = int(max(0, np.floor(pts[:, 1].min()) - pad))
        x1 = int(min(w, np.ceil(pts[:, 0].max()) + pad))
        y1 = int(min(h, np.ceil(pts[:, 1].max()) + pad))
        if x1 - x0 < 80 or y1 - y0 < 80:
            return None
        # 面积占比过大时（比如标定异常给出整幅图）退回全图，避免白忙
        if (x1 - x0) * (y1 - y0) > 0.92 * w * h:
            return None
        return x0, y0, x1, y1

    def detect(self, frame_bgr, H) -> BoatPose | None:
        """
        检测船。返回 None 表示本帧没看到码。
        H 为像素 -> 水池米的单应性矩阵。
        """
        roi = self._search_roi(frame_bgr.shape, H)
        if roi is not None:
            x0, y0, x1, y1 = roi
            patch = frame_bgr[y0:y1, x0:x1]
        else:
            x0 = y0 = 0
            patch = frame_bgr
        gray = self._prepare_gray(patch)

        if self._detector is not None:
            corners, ids, _ = self._detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(gray, self._dict, parameters=self._params)

        if ids is None or len(ids) == 0:
            return self._fallback_pose()

        # 把 ROI 内的角点还原到整幅图坐标
        if roi is not None:
            offset = np.array([x0, y0], dtype=np.float32)
            corners = [c + offset for c in corners]

        # 只取目标 ID
        match = None
        for i, mid in enumerate(ids.flatten()):
            if int(mid) == self.marker_id:
                match = corners[i]
                break
        if match is None:
            return self._fallback_pose()

        quad = canonical_corners(match)       # 码自身的 tl, tr, br, bl（勿重排）
        center_px = quad.mean(axis=0)
        x, y = pixel_to_pool(H, center_px)

        heading = heading_from_corners(quad, H)

        # --- 低通滤波，抑制小码角点抖动引起的 PID 振荡 ---
        if self._heading is None:
            self._heading = heading
        else:
            # 角度差取最短路径，避免 359 -> 1 时跳变
            diff = (heading - self._heading + 180.0) % 360.0 - 180.0
            self._heading = (self._heading + HEADING_SMOOTHING * diff) % 360.0
        heading = self._heading

        self._remember(x, y, heading)
        return BoatPose(x=x, y=y, heading=heading, corner_count=4)

    def _remember(self, x: float, y: float, heading: float) -> None:
        """记录有效位姿，供丢帧时外推。"""
        now = time.monotonic()
        if self._last_pos is not None and self._last_pos_t is not None:
            dt = now - self._last_pos_t
            if 1e-3 < dt < 0.5:          # 只在合理间隔内估速度，避免跳变
                vx = (x - self._last_pos[0]) / dt
                vy = (y - self._last_pos[1]) / dt
                # 一阶低通，抑制单帧噪声
                self._last_vel = (
                    0.5 * vx + 0.5 * self._last_vel[0],
                    0.5 * vy + 0.5 * self._last_vel[1],
                )
        self._last_pos = (float(x), float(y))
        self._last_pos_t = now
        self._last_heading = float(heading)

    def _fallback_pose(self) -> "BoatPose | None":
        """丢码时的兜底：keep_ms 内按最后速度外推位置，航向保持不变。

        超过 keep_ms 才真正返回 None（上层据此判丢并重置规划）。
        """
        if self._last_pos is None or self._last_pos_t is None:
            return None
        age_ms = (time.monotonic() - self._last_pos_t) * 1000.0
        if age_ms > self.keep_ms:
            return None
        dt = age_ms / 1000.0
        # 外推距离做上限，避免长时间丢帧后飘出去
        max_drift = 0.05
        dx = self._last_vel[0] * dt
        dy = self._last_vel[1] * dt
        drift = math.hypot(dx, dy)
        if drift > max_drift:
            scale = max_drift / drift
            dx *= scale
            dy *= scale
        x = self._last_pos[0] + dx
        y = self._last_pos[1] + dy
        heading = self._last_heading if self._last_heading is not None else 0.0
        return BoatPose(x=x, y=y, heading=heading, corner_count=0)

    def reset_filter(self) -> None:
        """丢失目标后重置滤波器，避免下次出现时残留旧值。

        注意：这里**不清** _last_pos / _last_pos_t —— 丢帧延续要靠它们；
        真要清（比如切模式、船被拿走）调用 reset_tracking()。
        """
        self._heading = None

    def reset_tracking(self) -> None:
        """彻底清空跟踪状态（含丢帧延续历史）。"""
        self._heading = None
        self._last_pos = None
        self._last_pos_t = None
        self._last_vel = (0.0, 0.0)
        self._last_heading = None

    @staticmethod
    def draw(frame_bgr, corners_px: np.ndarray | None) -> None:
        if not HAS_CV2 or corners_px is None:
            return
        pts = corners_px.reshape(-1, 1, 2).astype(np.int32)
        cv2.polylines(frame_bgr, [pts], True, (0, 255, 0), 2)
