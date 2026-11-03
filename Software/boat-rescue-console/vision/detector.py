"""
落水目标检测（增强版）：多段 HSV + 水池 ROI + 形状打分 + 时序跟踪 + 可选 ONNX 人形后端

与 target.py 的关系
-------------------
target.py 是"能用就行"的最小实现：全图 HSV -> 取最大轮廓 -> 底部中心点。它有两个
现场很容易踩的坑：**画面里任何更大的橙色物体都会被当成落水者**（橙色救生圈、地上的
橙色插排、反光贴纸），以及**丢帧时继续沿用旧坐标最多 10 帧**。本模块不改变它的行为，
但提供一套可以直接替上去的实现：

1) **池外橙色物体**：用单应矩阵 H 的逆把水池矩形 (0..1.2 m) 投回像素，既做 ROI 裁剪，
   又做多边形掩膜。池外（含水池外接矩形内的斜角区域）的橙色一律丢弃——不会因为画面
   里别处有更大的橙色块而把船引向池外。
2) **水面高光 / 反光条**：多段 HSV（橙色主段 + 背光暗橙 + 强光偏黄橙）叠加形态学，
   再用轮廓打分（面积、长宽比、填充率、圆度、凸度）逐个拒绝，而不是"取最大轮廓"。
   反光条面积可能很大，但填充率 / 长宽比异常，会被拒掉。
3) **单帧抖动**：alpha-beta 滤波（位置 EMA + 速度估计）做时序跟踪并给出 track_id；
   丢失时 confidence 按帧衰减，超过 lost_frames 直接判丢并返回 None，不再长期沿用
   陈旧坐标。
4) **深度学习预留**：vision/models/ 下存在 yolov8n.onnx 之类的模型时，用 cv2.dnn 跑
   YOLOv8 person 检测（class 0），高置信时优先于颜色检测；没有模型就静默退回纯传统
   检测，**不引入 torch 依赖**。模型放置方式见 vision/models/README.md。

统一输出
--------
    Detection(x, y, area_px, bottom_px, confidence, source, track_id)
      x, y       水池米坐标（左下水池角为原点，X 右、Y 上，量程 1.2 m）
      area_px    目标像素面积（传统=轮廓面积；yolo=框面积，语义不同，仅作打分参考）
      bottom_px  目标轮廓/框的底边中点像素坐标（船要抵达的水面接触点）
      confidence 0~1
      source     "classical" / "yolo"
      track_id   跟踪编号（同一个目标在连续帧里保持不变）

用法
----
    from detector import Detector
    d = Detector()
    det = d.detect(frame_bgr, H)        # H: 像素 -> 水池米；返回 Detection | None

    # 现场调阈值（不传就用 config.TARGET_HSV_RANGES）
    d = Detector(hsv_ranges=[((5, 120, 120), (22, 255, 255))], min_area_px=400)

    # 离线回放录像：用固定 dt 而不是墙钟，速度估计才准
    d = Detector(fps=30.0)

    # 强制关掉 ONNX（例如只想比传统路径耗时）
    d = Detector(yolo_enabled=False)

耗时（1080P，实测值见 test_detector.py 末尾两行）
-----------------------------------------------
传统路径只处理水池 ROI（默认长边降采样到 1000 px），本机实测约 3 ms/帧；ONNX 前向
640x640 在 CPU 上约 30~40 ms，所以默认每 yolo_every=3 帧跑一次，摊到每帧约 15 ms
（含传统路径）。两档都在 30fps 预算内。
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:            # pragma: no cover - 没装 OpenCV 时仍可 import 本模块做静态检查
    cv2 = None
    HAS_CV2 = False

try:                           # 与 target.py / locator.py 一致的"同目录平铺导入"风格
    import config
    from pool import POOL_SIZE_M, pixel_to_pool
except ImportError:            # pragma: no cover - 作为包（vision.detector）导入时
    from . import config                                    # type: ignore
    from .pool import POOL_SIZE_M, pixel_to_pool            # type: ignore

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().with_name("models")

# vision/models/ 下的模型搜索顺序（先小后大：1080P 下 yolov8n 已经够用）
YOLO_MODEL_NAMES = (
    "yolov8n.onnx",
    "yolo11n.onnx",
    "yolov8s.onnx",
    "yolo11s.onnx",
    "person.onnx",
)

# 内置多段 HSV。OpenCV 的 H 是 0~179，S/V 是 0~255。
# 所有段的 S/V 下限都在 110 以上：水面镜面高光虽然很亮，但饱和度低，会被 S 下限
# 直接挡掉，这比事后靠形态学去碎斑可靠得多。
# 注意：H 跨越 0/179 的颜色（正红）必须写成两段；单段里 lo.H > hi.H 是无效的。
DEFAULT_HSV_RANGES: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = (
    ((5, 110, 110), (24, 255, 255)),      # 橙色主段（标准橙色浮球/救生衣）
    ((0, 130, 150), (5, 255, 255)),       # 背光侧的偏红橙
    ((24, 120, 120), (32, 255, 255)),     # 强光侧的偏黄金橙
)

# 形状打分的饱和点（这些是"够好"的参考值，不是硬阈值）
_FILL_GOOD = 0.85
_CIRC_GOOD = 0.75
_SOLIDITY_GOOD = 0.95

# 同一个进程里只提示一次的状态提示（缺模型/加载失败/已启用）
_NOTE_ONCE_SEEN: set[str] = set()

__all__ = ["Detection", "Detector", "DEFAULT_HSV_RANGES", "MODELS_DIR", "YOLO_MODEL_NAMES"]


def _clamp(value: float, lo: float, hi: float) -> float:
    return lo if value < lo else (hi if value > hi else value)


def _odd(value: float) -> int:
    """向上取到奇数：OpenCV 的结构元素边长必须是奇数。"""
    n = int(round(value))
    if n < 1:
        return 1
    return n if n % 2 == 1 else n + 1


def _normalize_ranges(ranges) -> tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]:
    """把 HSV 段规整成 (lo, hi) 元组并做合法性检查。"""
    out = []
    for item in ranges:
        if len(item) != 2:
            raise ValueError(f"HSV 段必须是 (lo, hi) 两个三元组，收到: {item!r}")
        lo, hi = item
        lo = tuple(int(v) for v in lo)
        hi = tuple(int(v) for v in hi)
        if len(lo) != 3 or len(hi) != 3:
            raise ValueError(f"HSV 段必须是 3 通道 (H,S,V)，收到: {item!r}")
        if not (0 <= lo[0] <= hi[0] <= 179):
            raise ValueError(
                f"HSV 段的 H 必须满足 0 <= H_min <= H_max <= 179（红色这类跨 0/179 的"
                f"颜色请拆成两段），收到: {item!r}"
            )
        if any(not (0 <= v <= 255) for v in (*lo, *hi)):
            raise ValueError(f"HSV 的 S/V 必须在 0~255，收到: {item!r}")
        out.append((lo, hi))
    if not out:
        raise ValueError("HSV 段不能为空")
    return tuple(out)


def _dedup_ranges(ranges) -> tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...]:
    seen: set[tuple] = set()
    out = []
    for lo, hi in ranges:
        if (lo, hi) in seen:
            continue
        seen.add((lo, hi))
        out.append((lo, hi))
    return tuple(out)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------
@dataclass
class Detection:
    """统一检测结果（传统 / YOLO 共用）。坐标单位是米，水池左下角为原点。"""

    x: float                              # 水池 X（米）
    y: float                              # 水池 Y（米）
    area_px: float                        # 目标像素面积（传统=轮廓面积，yolo=框面积）
    bottom_px: tuple[int, int]            # 底边中点像素坐标（水面接触点）
    confidence: float                     # 0~1
    source: str                           # "classical" / "yolo"
    track_id: int | None = None           # 跟踪编号
    box_px: tuple[int, int, int, int] | None = None   # 像素框 (x1,y1,x2,y2)，供可视化

    def as_tuple(self) -> tuple[float, float]:
        return self.x, self.y


@dataclass
class _Candidate:
    """单帧观测（还没进跟踪器）。"""

    x: float
    y: float
    area_px: float
    bottom_px: tuple[int, int]
    confidence: float
    source: str
    box_px: tuple[int, int, int, int] | None = None


@dataclass
class _Track:
    """一条轨迹：alpha-beta 滤波后的位置 + 速度估计。"""

    track_id: int
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    confidence: float = 0.0
    hits: int = 0
    misses: int = 0
    area_px: float = 0.0
    bottom_px: tuple[int, int] = (0, 0)
    source: str = "classical"
    box_px: tuple[int, int, int, int] | None = None


@dataclass(frozen=True)
class _Roi:
    """水池 ROI 的像素几何（按 H 缓存，H 不变就不重算）。"""

    x0: int
    y0: int
    x1: int                     # 开区间
    y1: int                     # 开区间
    mask: np.ndarray            # ROI 局部坐标下的水池多边形掩膜（全分辨率）
    sx: float                   # 工作分辨率 / 全分辨率（x）
    sy: float                   # 工作分辨率 / 全分辨率（y）
    work_w: int
    work_h: int

    @property
    def area_factor(self) -> float:
        """工作分辨率面积 -> 全分辨率面积 的系数。"""
        return 1.0 / max(1e-12, self.sx * self.sy)


# ---------------------------------------------------------------------------
# 检测器
# ---------------------------------------------------------------------------
class Detector:
    """
    目标检测器：传统检测（默认）+ 可选 ONNX person 后端 + 跟踪。

    所有阈值都能从构造参数覆盖；不传时优先读 config.py，读不到用模块内置默认值。
    """

    def __init__(
        self,
        *,
        # ---------------- 传统检测 ----------------
        hsv_ranges=None,
        multi_segment: bool = True,
        min_area_px: int | None = None,
        morph_kernel: int | None = None,
        pool_size_m: float | None = None,
        pool_margin_m: float = 0.05,
        roi_max_side: int = 1000,
        roi_pad_px: int = 8,
        # ---------------- 形状打分 ----------------
        min_fill: float = 0.32,
        min_circularity: float = 0.12,
        min_solidity: float = 0.55,
        min_aspect: float = 0.25,
        max_aspect: float = 4.0,
        area_saturation: float = 4.0,
        # ---------------- 跟踪 ----------------
        lost_frames: int | None = None,
        ema_alpha: float = 0.55,
        vel_beta: float = 0.18,
        vel_decay: float = 0.5,
        max_speed_mps: float = 2.0,
        gate_m: float = 0.22,
        conf_decay: float = 0.80,
        fps: float | None = None,
        max_dt_s: float = 0.5,
        # ---------------- ONNX ----------------
        model_path=None,
        yolo_enabled: bool = True,
        yolo_every: int = 3,
        yolo_conf: float = 0.35,
        yolo_iou: float = 0.45,
        yolo_priority_conf: float = 0.45,
        yolo_classes=(0,),
        yolo_input_size: int = 640,
        yolo_max_frame_side: int = 1280,
        # ---------------- 杂项 ----------------
        verbose: bool = False,
    ) -> None:
        if not HAS_CV2:
            raise RuntimeError("Detector 需要 OpenCV，请先安装: pip install opencv-python")

        # ---- 从 config 取默认值（现场校准的值优先） ----
        if min_area_px is None:
            min_area_px = int(getattr(config, "MIN_TARGET_AREA_PX", 300))
        if morph_kernel is None:
            morph_kernel = int(getattr(config, "MORPH_KERNEL", 5))
        if lost_frames is None:
            lost_frames = int(getattr(config, "TARGET_LOST_FRAMES", 10))
        if pool_size_m is None:
            pool_size_m = float(POOL_SIZE_M)

        self.min_area_px = int(min_area_px)
        self.morph_kernel = int(morph_kernel)
        self.lost_frames = max(1, int(lost_frames))
        self.pool_size_m = float(pool_size_m)
        self.pool_margin_m = float(pool_margin_m)
        # 水池多边形（米坐标）；由标定文件 pool_polygon_m 注入，None 时走矩形范围判定
        self._pool_polygon = None
        self.roi_max_side = max(64, int(roi_max_side))
        self.roi_pad_px = max(0, int(roi_pad_px))

        # ---- HSV ----
        if hsv_ranges is None:
            cfg_ranges = getattr(config, "TARGET_HSV_RANGES", None) or ()
            cfg_ranges = tuple(
                (tuple(int(v) for v in lo), tuple(int(v) for v in hi)) for lo, hi in cfg_ranges
            )
            if cfg_ranges and multi_segment:
                # 现场校准的主段 + 内置补充段：既尊重现场标定，又保留多段能力
                ranges = _dedup_ranges(_normalize_ranges(cfg_ranges) + DEFAULT_HSV_RANGES)
            elif cfg_ranges:
                ranges = _normalize_ranges(cfg_ranges)
            else:
                ranges = DEFAULT_HSV_RANGES if multi_segment else DEFAULT_HSV_RANGES[:1]
        else:
            ranges = _normalize_ranges(hsv_ranges)
        self.hsv_ranges = tuple(ranges)
        self._lo = [np.array(lo, dtype=np.uint8) for lo, _ in self.hsv_ranges]
        self._hi = [np.array(hi, dtype=np.uint8) for _, hi in self.hsv_ranges]

        # ---- 形状阈值 ----
        self.min_fill = float(min_fill)
        self.min_circularity = float(min_circularity)
        self.min_solidity = float(min_solidity)
        self.min_aspect = float(min_aspect)
        self.max_aspect = float(max_aspect)
        if self.max_aspect <= 1.0:
            raise ValueError("max_aspect 必须 > 1.0")
        self.area_saturation = max(1.0, float(area_saturation))

        # ---- 跟踪 ----
        self.ema_alpha = _clamp(float(ema_alpha), 0.01, 1.0)
        self.vel_beta = _clamp(float(vel_beta), 0.0, 1.0)
        self.vel_decay = _clamp(float(vel_decay), 0.0, 1.0)
        self.max_speed_mps = float(max_speed_mps)
        self.gate_m = max(0.01, float(gate_m))
        self.conf_decay = _clamp(float(conf_decay), 0.0, 1.0)
        self.fps = None if fps is None else float(fps)
        if self.fps is not None and self.fps <= 0:
            raise ValueError("fps 必须 > 0（None 表示按墙钟计 dt）")
        self.max_dt_s = max(1e-3, float(max_dt_s))

        self._tracks: list[_Track] = []
        self._next_track_id = 1
        self._last_time: float | None = None

        # ---- ROI 缓存（H 每帧都是同一个对象内容，命中后零开销） ----
        self._roi_key: tuple | None = None
        self._roi_cache: _Roi | None = None

        # ---- ONNX ----
        self.verbose = bool(verbose)
        self._yolo_requested = bool(yolo_enabled)
        self.yolo_enabled = False            # 实际生效状态，加载成功后才置 True
        self.yolo_every = max(1, int(yolo_every))
        self.yolo_conf = _clamp(float(yolo_conf), 0.0, 1.0)
        self.yolo_iou = _clamp(float(yolo_iou), 0.0, 1.0)
        self.yolo_priority_conf = _clamp(float(yolo_priority_conf), 0.0, 1.0)
        self.yolo_classes = tuple(int(c) for c in yolo_classes) if yolo_classes is not None else None
        self.yolo_input_size = int(yolo_input_size)
        self.yolo_max_frame_side = max(64, int(yolo_max_frame_side))
        self.model_path = model_path
        self._net = None
        self._model_file: Path | None = None
        self._yolo_tick = 0
        self._yolo_cache: _Candidate | None = None
        self._yolo_cache_ready = False
        self._yolo_cache_shape: tuple[int, ...] | None = None
        self.notes: list[str] = []
        self.last_detect_ms: float = 0.0
        self.frames: int = 0

        if self._yolo_requested:
            self._init_yolo()

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def detect(self, frame_bgr, H) -> Detection | None:
        """
        检测一帧。返回 None 表示"当前没有可信目标"（含丢失超时）。

        :param frame_bgr: BGR 图像（HxWx3，uint8）；灰度/ BGRA 也能吃，会内部转换。
        :param H: 3x3 单应矩阵，像素 -> 水池米（与 pool.compute_homography 一致）。
        """
        if frame_bgr is None:
            raise ValueError("frame_bgr 不能为 None")
        if not HAS_CV2:
            raise RuntimeError("Detector 需要 OpenCV，请先安装: pip install opencv-python")

        t_start = time.perf_counter()
        frame = self._as_bgr(frame_bgr)
        H = self._as_homography(H)
        dt = self._time_step()

        candidate = self._detect_classical(frame, H)

        if self.yolo_enabled:
            yolo = self._detect_yolo(frame, H)
            if yolo is not None:
                if yolo.confidence >= self.yolo_priority_conf:
                    # 人形高置信：优先于颜色检测（颜色段对救生衣/皮肤并不可靠）
                    candidate = yolo
                elif candidate is None:
                    # 颜色检测什么都没找到，低置信人形也比 None 有用
                    candidate = yolo

        detection = self._update_tracks(candidate, dt)
        self.frames += 1
        self.last_detect_ms = (time.perf_counter() - t_start) * 1000.0
        return detection

    def reset(self) -> None:
        """清空跟踪状态（切换场景 / 重新标定后调用）。"""
        self._tracks.clear()
        self._next_track_id = 1
        self._last_time = None
        self._roi_key = None
        self._roi_cache = None
        self._yolo_tick = 0
        self._yolo_cache = None
        self._yolo_cache_ready = False
        self._yolo_cache_shape = None

    def track_state(self) -> list[dict]:
        """当前所有轨迹的快照（调试/画速度箭头用）。"""
        return [
            {
                "track_id": t.track_id,
                "x": t.x,
                "y": t.y,
                "vx": t.vx,
                "vy": t.vy,
                "speed": math.hypot(t.vx, t.vy),
                "confidence": t.confidence,
                "hits": t.hits,
                "misses": t.misses,
                "source": t.source,
            }
            for t in self._tracks
        ]

    def info(self) -> dict:
        """当前配置与后端状态（前端/日志用）。"""
        return {
            "hsv_ranges": [[list(lo), list(hi)] for lo, hi in self.hsv_ranges],
            "min_area_px": self.min_area_px,
            "morph_kernel": self.morph_kernel,
            "lost_frames": self.lost_frames,
            "pool_size_m": self.pool_size_m,
            "roi_max_side": self.roi_max_side,
            "fps": self.fps,
            "yolo_requested": self._yolo_requested,
            "yolo_enabled": self.yolo_enabled,
            "yolo_model": str(self._model_file) if self._model_file else None,
            "yolo_every": self.yolo_every,
            "active_tracks": len(self._tracks),
            "frames": self.frames,
            "last_detect_ms": round(self.last_detect_ms, 3),
            "notes": list(self.notes),
        }

    # ------------------------------------------------------------------
    # 输入规整
    # ------------------------------------------------------------------
    @staticmethod
    def _as_bgr(frame_bgr) -> np.ndarray:
        frame = frame_bgr
        if not isinstance(frame, np.ndarray):
            frame = np.asarray(frame)
        if frame.ndim == 2:
            frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
        elif frame.ndim == 3 and frame.shape[2] == 4:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
        elif frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError(f"不支持的帧形状: {frame.shape}，需要 HxWx3 BGR")
        if frame.dtype != np.uint8:
            # 相机给的是 uint8；其它位深按 0~255 饱和截断，避免 cvtColor 直接报错
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        return frame

    @staticmethod
    def _as_homography(H) -> np.ndarray:
        arr = np.asarray(H, dtype=np.float64)
        if arr.shape != (3, 3):
            raise ValueError(f"单应矩阵 H 必须是 3x3，收到 {arr.shape}")
        if not np.all(np.isfinite(arr)):
            raise ValueError("单应矩阵 H 含有 NaN/Inf，请重新标定")
        return arr

    def _time_step(self) -> float:
        """估算帧间隔 dt（秒）。fps 给定时用固定值，便于离线回放。"""
        now = time.perf_counter()
        if self.fps is not None:
            dt = 1.0 / self.fps
        elif self._last_time is None:
            dt = 1.0 / 30.0
        else:
            dt = now - self._last_time
        self._last_time = now
        return _clamp(dt, 1.0 / 240.0, self.max_dt_s)

    # ------------------------------------------------------------------
    # 水池 ROI
    # ------------------------------------------------------------------
    def _roi(self, frame_shape, H: np.ndarray) -> _Roi | None:
        """把水池矩形 (0..pool_size) 用 H 的逆投回像素，得到 ROI 裁剪框 + 多边形掩膜。"""
        h, w = int(frame_shape[0]), int(frame_shape[1])
        key = (h, w, H.tobytes())
        if self._roi_key == key:
            return self._roi_cache

        self._roi_key = key
        self._roi_cache = None
        try:
            Hinv = np.linalg.inv(H)
        except np.linalg.LinAlgError:
            return None
        if not np.all(np.isfinite(Hinv)):
            return None

        L = self.pool_size_m
        corners_m = np.array([[0, 0], [L, 0], [L, L], [0, L]], dtype=np.float32).reshape(-1, 1, 2)
        try:
            pts = cv2.perspectiveTransform(corners_m, Hinv.astype(np.float32)).reshape(-1, 2)
        except cv2.error:      # pragma: no cover - 极端退化矩阵
            return None
        if not np.all(np.isfinite(pts)):
            return None

        pad = self.roi_pad_px
        x0 = max(0, int(math.floor(float(pts[:, 0].min()))) - pad)
        y0 = max(0, int(math.floor(float(pts[:, 1].min()))) - pad)
        x1 = min(w, int(math.ceil(float(pts[:, 0].max()))) + pad)
        y1 = min(h, int(math.ceil(float(pts[:, 1].max()))) + pad)
        if x1 - x0 < 8 or y1 - y0 < 8:
            # 水池完全不在画面内（或小到没法检测）
            return None

        mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        local = pts - np.array([x0, y0], dtype=np.float32)
        cv2.fillPoly(mask, [np.round(local).astype(np.int32)], 255)

        rw, rh = x1 - x0, y1 - y0
        scale = min(1.0, float(self.roi_max_side) / float(max(rw, rh)))
        scale = max(scale, 0.05)
        work_w = max(8, int(round(rw * scale)))
        work_h = max(8, int(round(rh * scale)))

        roi = _Roi(
            x0=x0, y0=y0, x1=x1, y1=y1, mask=mask,
            sx=work_w / float(rw), sy=work_h / float(rh),
            work_w=work_w, work_h=work_h,
        )
        self._roi_cache = roi
        return roi

    def set_pool_polygon(self, polygon_m) -> None:
        """注入水池轮廓（米坐标，Nx2）。传 None 清除，回到矩形范围判定。

        标定文件里存了 pool_polygon_m 时，locator 会调用本方法；
        非矩形水池（圆角/梯形）必须用多边形，否则池壁附近的有效目标会被判成池外。
        """
        if polygon_m is None:
            self._pool_polygon = None
            return
        try:
            import numpy as _np
            arr = _np.asarray(polygon_m, dtype=_np.float32).reshape(-1, 2)
        except Exception:
            self._pool_polygon = None
            return
        self._pool_polygon = arr if len(arr) >= 3 else None

    def _in_pool(self, x: float, y: float) -> bool:
        """目标米坐标是否落在水池内。

        优先用多边形判定（标定文件里存了 pool_polygon_m 时）：现场水池常是
        圆角/梯形，用矩形范围判断会把池壁附近的有效目标误判成池外，表现就是
        "船靠近池壁就丢目标"。没有多边形时退回矩形范围（兼容老标定）。
        """
        m = self.pool_margin_m
        polygon = getattr(self, "_pool_polygon", None)
        if polygon is not None and len(polygon) >= 3:
            try:
                import cv2 as _cv2
                pt = (float(x), float(y))
                # 正数=内部；margin 视作"允许略微出界"（容差）
                return _cv2.pointPolygonTest(polygon, pt, True) >= -m
            except Exception:
                pass
        return -m <= x <= self.pool_size_m + m and -m <= y <= self.pool_size_m + m

    # ------------------------------------------------------------------
    # 传统检测
    # ------------------------------------------------------------------
    def _detect_classical(self, frame: np.ndarray, H: np.ndarray) -> _Candidate | None:
        roi = self._roi(frame.shape, H)
        if roi is None:
            return None

        patch = frame[roi.y0:roi.y1, roi.x0:roi.x1]
        if patch.size == 0:
            return None

        if roi.sx < 0.999 or roi.sy < 0.999:
            patch = cv2.resize(patch, (roi.work_w, roi.work_h), interpolation=cv2.INTER_AREA)
            poly = cv2.resize(roi.mask, (roi.work_w, roi.work_h), interpolation=cv2.INTER_NEAREST)
        else:
            poly = roi.mask
        if patch.size == 0:
            return None

        # --- 多段 HSV ---
        hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
        color = cv2.inRange(hsv, self._lo[0], self._hi[0])
        for lo, hi in zip(self._lo[1:], self._hi[1:]):
            color = cv2.bitwise_or(color, cv2.inRange(hsv, lo, hi))

        # --- 水池多边形掩膜：先裁掉池外（含外接矩形的斜角），再做形态学 ---
        # 顺序很重要：先掩膜再闭运算，否则池外的大块橙色会和池内目标在边界"连"起来。
        mask = cv2.bitwise_and(color, poly)

        k_full = self.morph_kernel
        if k_full > 0:
            k = max(3, _odd(k_full * min(roi.sx, roi.sy)))
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)     # 去掉高光碎斑
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)    # 补上目标内部空洞

        # RETR_CCOMP 而不是 RETR_EXTERNAL：空心轮廓（细边框、反光环）的外轮廓面积包含
        # 内部空洞，直接用会把它当成实心大目标。这里把子轮廓（空洞）面积减掉，
        # "面积/填充率"才对应"真正是橙色的像素"。只处理外轮廓（parent == -1）。
        contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        hierarchy = hierarchy[0] if hierarchy is not None else None

        hole_area: dict[int, float] = {}
        if hierarchy is not None:
            for i, node in enumerate(hierarchy):
                parent = int(node[3])
                if parent >= 0:
                    hole_area[parent] = hole_area.get(parent, 0.0) + cv2.contourArea(contours[i])

        min_area_work = self.min_area_px * roi.sx * roi.sy * 0.5   # 提前剪枝，少算无用轮廓
        best: _Candidate | None = None
        for idx, contour in enumerate(contours):
            if hierarchy is not None and int(hierarchy[idx][3]) != -1:
                continue                                  # 内轮廓（空洞）不当目标
            area_work = cv2.contourArea(contour) - hole_area.get(idx, 0.0)
            if area_work < min_area_work:
                continue
            if area_work <= 1e-6:
                continue

            x, y, bw, bh = cv2.boundingRect(contour)
            if bw <= 1 or bh <= 1:
                continue
            area_px = area_work * roi.area_factor
            if area_px < self.min_area_px:
                continue

            # --- 形状打分：面积、长宽比、填充率、圆度、凸度 ---
            aspect = bw / float(bh)
            if aspect < self.min_aspect or aspect > self.max_aspect:
                continue
            fill = area_work / float(bw * bh)
            if fill < self.min_fill:
                continue
            perimeter = cv2.arcLength(contour, True)
            if perimeter <= 1e-6:
                continue
            circularity = 4.0 * math.pi * area_work / (perimeter * perimeter)
            if circularity < self.min_circularity:
                continue
            hull_area = cv2.contourArea(cv2.convexHull(contour))
            if hull_area <= 1e-6:
                continue
            solidity = area_work / hull_area
            if solidity < self.min_solidity:
                continue

            # --- 底边中点 -> 水池坐标（几何围栏再兜一次底） ---
            bottom_px = (
                int(round(roi.x0 + (x + bw / 2.0) / roi.sx)),
                int(round(roi.y0 + (y + bh) / roi.sy)),
            )
            px, py = pixel_to_pool(H, bottom_px)
            if not self._in_pool(px, py):
                continue

            confidence = self._shape_confidence(area_px, fill, circularity, solidity, aspect)
            if best is None or confidence > best.confidence:
                best = _Candidate(
                    x=float(px), y=float(py), area_px=float(area_px),
                    bottom_px=bottom_px, confidence=confidence, source="classical",
                )
        return best

    def _shape_confidence(self, area_px: float, fill: float, circularity: float,
                          solidity: float, aspect: float) -> float:
        """把形状指标压成 0~1 的置信度（面积饱和 + 形状越好分越高）。"""
        area_score = _clamp(area_px / (self.area_saturation * self.min_area_px), 0.0, 1.0)
        fill_score = _clamp((fill - self.min_fill) / max(1e-6, _FILL_GOOD - self.min_fill), 0.0, 1.0)
        circ_score = _clamp((circularity - self.min_circularity)
                            / max(1e-6, _CIRC_GOOD - self.min_circularity), 0.0, 1.0)
        solid_score = _clamp((solidity - self.min_solidity)
                             / max(1e-6, _SOLIDITY_GOOD - self.min_solidity), 0.0, 1.0)
        aspect_score = _clamp(1.0 - abs(aspect - 1.0) / max(1e-6, self.max_aspect - 1.0), 0.0, 1.0)
        conf = (0.30 * area_score + 0.20 * fill_score + 0.15 * circ_score
                + 0.15 * solid_score + 0.20 * aspect_score)
        return _clamp(conf, 0.02, 0.99)

    # ------------------------------------------------------------------
    # ONNX（YOLOv8 person）
    # ------------------------------------------------------------------
    def _note_once(self, key: str, message: str) -> None:
        """同一个进程只提示一次；每次实例化都会记进 self.notes 方便 UI 展示。"""
        self.notes.append(message)
        log.info(message)
        if key in _NOTE_ONCE_SEEN:
            return
        _NOTE_ONCE_SEEN.add(key)
        # 默认打一行：模型缺失是"静默禁用"，但用户至少要知道为什么没有人形检测
        print(f"[detector] {message}")

    def _find_model(self) -> Path | None:
        if self.model_path is not None:
            path = Path(self.model_path)
            if not path.is_absolute():
                path = MODELS_DIR / path
            return path if path.is_file() else None
        if not MODELS_DIR.is_dir():
            return None
        for name in YOLO_MODEL_NAMES:
            candidate = MODELS_DIR / name
            if candidate.is_file():
                return candidate
        extra = sorted(MODELS_DIR.glob("*.onnx"))
        return extra[0] if extra else None

    def _init_yolo(self) -> None:
        path = self._find_model()
        if path is None:
            self.yolo_enabled = False
            where = (f"指定的模型路径不存在: {self.model_path}" if self.model_path is not None
                     else f"未找到 ONNX person 模型（目录 {MODELS_DIR}）")
            self._note_once(
                "no_model",
                f"{where}；YOLO 后端已禁用，仅用传统检测。放置方法见 vision/models/README.md",
            )
            return
        try:
            net = cv2.dnn.readNetFromONNX(str(path))
            # OpenCV 5 的新图引擎不支持 setPreferableTarget（会打 WARN），5 以下才设。
            try:
                major = int(str(cv2.__version__).split(".")[0])
            except (AttributeError, ValueError):      # pragma: no cover
                major = 4
            if major < 5:
                net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
                net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except Exception as exc:                     # noqa: BLE001 - 任何加载失败都应降级
            self.yolo_enabled = False
            self._note_once("load_failed", f"加载 ONNX 模型失败（{path}）：{exc}；YOLO 后端已禁用")
            return
        self._net = net
        self._model_file = path
        self.yolo_enabled = True

        # 自动校正输入尺寸：自定义模型可能是 320/224，配置里忘了改 YOLO_INPUT_SIZE
        # 就会用错尺寸（网络仍能前向，但框会整体缩放错，且不报错）——这里直接读 ONNX
        # 输入形状纠正；没装 onnx 或读不到就保持配置值。
        detected_size = self._detect_model_input_size(path)
        if detected_size and detected_size != self.yolo_input_size:
            self._note_once(
                "size_fix",
                f"模型输入尺寸是 {detected_size}，与配置的 {self.yolo_input_size} 不一致；"
                f"已自动改用 {detected_size}（建议把 config.YOLO_INPUT_SIZE 也改成 {detected_size}）",
            )
            self.yolo_input_size = detected_size

        self._note_once(
            "loaded",
            f"YOLO 后端已启用: {path.name}（每 {self.yolo_every} 帧推理一次，"
            f"输入 {self.yolo_input_size}，只取 class 0 person）",
        )

    @staticmethod
    def _detect_model_input_size(path) -> int | None:
        """从 ONNX 图输入读取方阵边长（224/320/640）。读不到返回 None。"""
        try:
            import onnx                     # 可选依赖：只用于读输入 shape
        except ImportError:
            return None
        try:
            model = onnx.load(str(path), load_external_data=False)
            dims = [dim.dim_value for dim in model.graph.input[0].type.tensor_type.shape.dim]
        except Exception:                   # noqa: BLE001 - 损坏/外部数据等，静默跳过
            return None
        if len(dims) == 4 and dims[2] and dims[3] and dims[2] == dims[3]:
            return int(dims[2])
        return None

    @staticmethod
    def decode_yolo_output(output, conf_thres: float = 0.35, classes=(0,)) -> list[tuple]:
        """
        解码 YOLOv8 原始输出。

        :param output: ndarray，形如 (1, 84, N) 或 (1, N, 84)，4 个框参数 + nc 个类别分数。
        :param conf_thres: 置信度阈值（YOLOv8 的类别分数已经是 sigmoid 后的概率）。
        :param classes: 只保留这些类别（None=全部）。
        :return: [(x1, y1, x2, y2, conf, cls)]，坐标是网络输入（letterbox 后）的像素。
        """
        arr = np.asarray(output)
        if arr.ndim == 3:
            arr = arr[0]
        if arr.ndim != 2:
            return []
        # 区分 "N x attrs" 与 "attrs x N"：attrs（4+类别数）通常远小于锚点数
        if arr.shape[0] > arr.shape[1] and arr.shape[1] <= 256:
            pass                                    # 已经是 N x attrs
        elif arr.shape[0] <= 256 and arr.shape[1] > arr.shape[0]:
            arr = arr.T
        if arr.shape[1] < 5:
            return []

        boxes = arr[:, :4].astype(np.float64)
        cls_scores = arr[:, 4:]
        if cls_scores.shape[1] == 1:
            conf = cls_scores[:, 0]
            cls = np.zeros(conf.shape, dtype=np.int32)
        else:
            cls = cls_scores.argmax(axis=1).astype(np.int32)
            conf = cls_scores[np.arange(cls_scores.shape[0]), cls]

        keep = np.isfinite(conf) & (conf >= conf_thres)
        if classes is not None:
            whitelist = np.asarray(list(classes), dtype=np.int32)
            if whitelist.size == 0:
                return []
            keep &= np.isin(cls, whitelist)
        if not np.any(keep):
            return []

        boxes = boxes[keep]
        conf = conf[keep]
        cls = cls[keep]
        cx, cy, bw, bh = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        valid = np.isfinite(boxes).all(axis=1) & (bw > 0) & (bh > 0)
        if not np.any(valid):
            return []
        cx, cy, bw, bh, conf, cls = cx[valid], cy[valid], bw[valid], bh[valid], conf[valid], cls[valid]

        # 按置信度降序，只留前 300 个，NMS 之前先削掉没用的
        order = np.argsort(-conf)[:300]
        out = []
        for i in order:
            out.append((
                float(cx[i] - bw[i] / 2.0),
                float(cy[i] - bh[i] / 2.0),
                float(cx[i] + bw[i] / 2.0),
                float(cy[i] + bh[i] / 2.0),
                float(conf[i]),
                int(cls[i]),
            ))
        return out

    @staticmethod
    def _letterbox(img: np.ndarray, new_size: int):
        """等比缩放到 new_size 并灰边填充（YOLO 训练时的预处理方式）。"""
        h, w = img.shape[:2]
        ratio = min(new_size / float(w), new_size / float(h))
        nw, nh = int(round(w * ratio)), int(round(h * ratio))
        nw, nh = max(1, min(new_size, nw)), max(1, min(new_size, nh))
        resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else img
        dw, dh = (new_size - nw) / 2.0, (new_size - nh) / 2.0
        left, top = int(round(dw - 0.1)), int(round(dh - 0.1))
        right, bottom = int(round(dw + 0.1)), int(round(dh + 0.1))
        padded = cv2.copyMakeBorder(resized, top, bottom, left, right,
                                    cv2.BORDER_CONSTANT, value=(114, 114, 114))
        return padded, ratio, left, top

    def _yolo_infer(self, frame: np.ndarray, H: np.ndarray) -> _Candidate | None:
        """跑一次 YOLOv8 前向，返回池内置信度最高的 person 候选。"""
        if self._net is None:
            return None
        h0, w0 = frame.shape[:2]
        frame_scale = min(1.0, float(self.yolo_max_frame_side) / float(max(h0, w0)))
        if frame_scale < 0.999:
            small = cv2.resize(
                frame,
                (max(1, int(round(w0 * frame_scale))), max(1, int(round(h0 * frame_scale)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            small = frame

        padded, ratio, pad_x, pad_y = self._letterbox(small, self.yolo_input_size)
        blob = cv2.dnn.blobFromImage(
            padded, 1.0 / 255.0, (self.yolo_input_size, self.yolo_input_size),
            swapRB=True, crop=False,
        )
        try:
            self._net.setInput(blob)
            outputs = self._net.forward(self._net.getUnconnectedOutLayersNames())
        except cv2.error as exc:                       # pragma: no cover - 模型/输入不匹配
            self._note_once("infer_failed", f"ONNX 推理失败：{exc}；YOLO 后端已禁用")
            self.yolo_enabled = False
            return None

        raw: list[tuple] = []
        for output in outputs:
            raw.extend(self.decode_yolo_output(output, self.yolo_conf, self.yolo_classes))
        if not raw:
            return None

        # letterbox 坐标 -> 原图坐标
        inv = 1.0 / max(1e-9, ratio * frame_scale)
        boxes_xywh: list[list[float]] = []
        scores: list[float] = []
        for x1, y1, x2, y2, conf, _cls in raw:
            X1 = _clamp((x1 - pad_x) * inv, 0.0, w0 - 1.0)
            Y1 = _clamp((y1 - pad_y) * inv, 0.0, h0 - 1.0)
            X2 = _clamp((x2 - pad_x) * inv, 0.0, w0 - 1.0)
            Y2 = _clamp((y2 - pad_y) * inv, 0.0, h0 - 1.0)
            w = X2 - X1
            h = Y2 - Y1
            if w < 2.0 or h < 2.0:
                continue
            boxes_xywh.append([X1, Y1, w, h])
            scores.append(conf)
        if not boxes_xywh:
            return None

        try:
            keep = cv2.dnn.NMSBoxes(boxes_xywh, scores, self.yolo_conf, self.yolo_iou)
        except cv2.error:                              # pragma: no cover - 空输入等
            keep = list(range(len(boxes_xywh)))
        if keep is None:
            return None
        keep_idx = np.asarray(keep).reshape(-1).astype(np.int32)
        if keep_idx.size == 0:
            return None

        best: _Candidate | None = None
        for i in keep_idx:
            if i < 0 or i >= len(boxes_xywh):
                continue
            bx, by, bw, bh = boxes_xywh[int(i)]
            bottom = (int(round(bx + bw / 2.0)), int(round(by + bh)))
            px, py = pixel_to_pool(H, bottom)
            if not self._in_pool(px, py):
                continue          # 池外人形（岸上/池外）直接丢掉，和传统路径同一道围栏
            conf = float(scores[int(i)])
            if best is None or conf > best.confidence:
                best = _Candidate(
                    x=float(px), y=float(py), area_px=float(bw * bh),
                    bottom_px=bottom, confidence=conf, source="yolo",
                    box_px=(int(round(bx)), int(round(by)),
                            int(round(bx + bw)), int(round(by + bh))),
                )
        return best

    def _detect_yolo(self, frame: np.ndarray, H: np.ndarray) -> _Candidate | None:
        """按 yolo_every 抽帧推理：中间帧复用上一次结果，摊平单帧耗时。"""
        if self._net is None:
            return None
        shape = tuple(frame.shape)
        if self._yolo_cache_shape != shape:
            self._yolo_cache = None
            self._yolo_cache_ready = False
            self._yolo_cache_shape = shape
            self._yolo_tick = 0
        self._yolo_tick += 1
        # 注意：缓存"没有检出"也是有效结果（ready=True, cache=None）。若只看 cache is None
        # 判断，会在持续无人的画面里每帧都重跑一次前向，白烧 30 ms。
        if self._yolo_cache_ready and (self._yolo_tick % self.yolo_every) != 0:
            return self._yolo_cache
        result = self._yolo_infer(frame, H)
        self._yolo_cache = result
        self._yolo_cache_ready = True
        return result

    # ------------------------------------------------------------------
    # 跟踪
    # ------------------------------------------------------------------
    def _associate(self, candidate: _Candidate, dt: float) -> _Track | None:
        """按"预测位置"的距离做门限关联（最近者胜）。"""
        best: _Track | None = None
        best_dist = float("inf")
        for track in self._tracks:
            pred_x = track.x + track.vx * dt
            pred_y = track.y + track.vy * dt
            dist = math.hypot(candidate.x - pred_x, candidate.y - pred_y)
            # 已经丢了 k 帧的轨迹放宽门限：短暂遮挡后还能接回同一个 track_id
            gate = self.gate_m + 0.08 * track.misses
            if dist <= gate and dist < best_dist:
                best, best_dist = track, dist
        return best

    def _apply_measurement(self, track: _Track, candidate: _Candidate, dt: float) -> None:
        """alpha-beta 滤波：位置 EMA（alpha）+ 速度估计（beta）。"""
        was_lost = track.misses > 0
        pred_x = track.x + track.vx * dt
        pred_y = track.y + track.vy * dt
        res_x = candidate.x - pred_x
        res_y = candidate.y - pred_y

        track.x = pred_x + self.ema_alpha * res_x
        track.y = pred_y + self.ema_alpha * res_y
        track.vx = _clamp(track.vx + self.vel_beta * res_x / dt, -self.max_speed_mps, self.max_speed_mps)
        track.vy = _clamp(track.vy + self.vel_beta * res_y / dt, -self.max_speed_mps, self.max_speed_mps)

        if was_lost:
            # 重新捕获：置信度直接对齐观测，避免带着衰减值爬回来
            track.confidence = candidate.confidence
        else:
            track.confidence = 0.65 * candidate.confidence + 0.35 * track.confidence
        track.misses = 0
        track.hits += 1
        track.area_px = candidate.area_px
        track.bottom_px = candidate.bottom_px
        track.source = candidate.source
        track.box_px = candidate.box_px

    def _update_tracks(self, candidate: _Candidate | None, dt: float) -> Detection | None:
        matched: _Track | None = None
        if candidate is not None:
            track = self._associate(candidate, dt)
            if track is None:
                track = _Track(
                    track_id=self._next_track_id,
                    x=candidate.x,
                    y=candidate.y,
                    confidence=candidate.confidence,
                    hits=1,
                    area_px=candidate.area_px,
                    bottom_px=candidate.bottom_px,
                    source=candidate.source,
                    box_px=candidate.box_px,
                )
                self._next_track_id += 1
                self._tracks.append(track)
            else:
                self._apply_measurement(track, candidate, dt)
            matched = track

        # 未匹配的轨迹：速度衰减、置信度按帧衰减（不长期沿用陈旧坐标）
        for track in self._tracks:
            if track is matched:
                continue
            track.misses += 1
            track.vx *= self.vel_decay
            track.vy *= self.vel_decay
            track.confidence *= self.conf_decay

        # 丢失超过 lost_frames 直接判丢
        if self.lost_frames > 0:
            self._tracks = [t for t in self._tracks if t.misses <= self.lost_frames]

        if not self._tracks:
            return None

        if matched is not None:
            track = matched
        else:
            track = max(self._tracks, key=lambda t: t.confidence)

        return Detection(
            x=track.x,
            y=track.y,
            area_px=track.area_px,
            bottom_px=track.bottom_px,
            confidence=_clamp(track.confidence, 0.0, 1.0),
            source=track.source,
            track_id=track.track_id,
            box_px=track.box_px,
        )
