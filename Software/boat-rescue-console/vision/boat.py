"""
船体检测：ArUco 码 -> 全局坐标 + 航向

航向为什么最容易出错（务必注意）：
  俯视相机里，小 ArUco 码的**偏航角分辨率很低**。5cm 的码在 1080P 俯拍下只有
  几十像素，角点抖动 1~2 px 就会带来好几度航向误差，而船端 PID 直接把它当
  `boat_heading` 用。航向噪声大 -> PID 持续振荡 -> 船在目标附近绕圈。
  本模块因此做了三件事：角点排序稳定、方向向量用两条边平均、航向低通滤波。

ArUco 方向约定：
  码的四个角按顺时针为 左上/右上/右下/左下。定义"船头"沿该顺序的
  左下 -> 左上 方向（即码的左侧边指向船头）。
  如果实测方向反了 90°/180°，改 HEADING_OFFSET_DEG 即可，不必改代码逻辑。
"""
from __future__ import annotations

import math
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
MARKER_SIZE_M = 0.05          # 5cm x 5cm

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


def _order_corners(corners: np.ndarray) -> np.ndarray:
    """
    把 4 个角点按 左上/右上/右下/左下 顺序排列。

    做法：先用 x+y 找左上（和最小）与右下（和最大），
    再用 y-x 找右上（差最小）与左下（差最大）。
    比单纯按角度排序更稳，因为航向计算依赖角点顺序一致。
    """
    pts = corners.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)     # y - x

    tl = pts[np.argmin(s)]
    br = pts[np.argmax(s)]
    tr = pts[np.argmin(d)]
    bl = pts[np.argmax(d)]
    return np.array([tl, tr, br, bl], dtype=np.float32)


class BoatDetector:
    def __init__(self, marker_id: int = MARKER_ID):
        if not HAS_CV2:
            raise RuntimeError("BoatDetector 需要 OpenCV，请先安装: pip install opencv-python")
        self.marker_id = marker_id
        self._dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        self._params = cv2.aruco.DetectorParameters()
        # 小码检测：降低最小周长阈值，提高自适应阈值窗口的鲁棒性
        self._params.adaptiveThreshWinSizeMin = 5
        self._params.adaptiveThreshWinSizeMax = 35
        self._params.adaptiveThreshWinSizeStep = 5
        self._params.minMarkerPerimeterRate = 0.01

        # OpenCV 4.7+ 用 ArucoDetector；旧版用 detectMarkers
        if hasattr(cv2.aruco, "ArucoDetector"):
            self._detector = cv2.aruco.ArucoDetector(self._dict, self._params)
        else:
            self._detector = None

        self._heading: float | None = None

    def detect(self, frame_bgr, H) -> BoatPose | None:
        """
        检测船。返回 None 表示本帧没看到码。
        H 为像素 -> 水池米的单应性矩阵。
        """
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)

        if self._detector is not None:
            corners, ids, _ = self._detector.detectMarkers(gray)
        else:
            corners, ids, _ = cv2.aruco.detectMarkers(gray, self._dict, parameters=self._params)

        if ids is None or len(ids) == 0:
            return None

        # 只取目标 ID
        match = None
        for i, mid in enumerate(ids.flatten()):
            if int(mid) == self.marker_id:
                match = corners[i]
                break
        if match is None:
            return None

        quad = _order_corners(match)          # tl, tr, br, bl
        center_px = quad.mean(axis=0)
        x, y = pixel_to_pool(H, center_px)

        # --- 航向 ---
        # 用"右侧边中点到左侧边中点"的方向作为船头方向，两条边平均可降低单点抖动。
        # 左右边中点：左边 = (tl+bl)/2，右边 = (tr+br)/2
        left_mid = (quad[0] + quad[3]) / 2.0
        right_mid = (quad[1] + quad[2]) / 2.0
        # 船头指向"左边中点"一侧（见模块注释的方向约定）
        v_px = left_mid - right_mid

        # 把方向向量映射到水池坐标系：取两点差值（不受平移影响）
        p0 = np.array([center_px[0], center_px[1]], dtype=np.float32)
        p1 = np.array([center_px[0] + v_px[0], center_px[1] + v_px[1]], dtype=np.float32)
        a = pixel_to_pool(H, p0)
        b = pixel_to_pool(H, p1)
        dx, dy = b[0] - a[0], b[1] - a[1]

        # 航向定义：0 指向 +Y，顺时针为正（与船端 atan2(dx,dy) 一致）
        heading = math.degrees(math.atan2(dx, dy))
        heading = (heading + HEADING_OFFSET_DEG) % 360.0

        # --- 低通滤波，抑制小码角点抖动引起的 PID 振荡 ---
        if self._heading is None:
            self._heading = heading
        else:
            # 角度差取最短路径，避免 359 -> 1 时跳变
            diff = (heading - self._heading + 180.0) % 360.0 - 180.0
            self._heading = (self._heading + HEADING_SMOOTHING * diff) % 360.0
        heading = self._heading

        return BoatPose(x=x, y=y, heading=heading, corner_count=4)

    def reset_filter(self) -> None:
        """丢失目标后重置滤波器，避免下次出现时残留旧值"""
        self._heading = None

    @staticmethod
    def draw(frame_bgr, corners_px: np.ndarray | None) -> None:
        if not HAS_CV2 or corners_px is None:
            return
        pts = corners_px.reshape(-1, 1, 2).astype(np.int32)
        cv2.polylines(frame_bgr, [pts], True, (0, 255, 0), 2)
