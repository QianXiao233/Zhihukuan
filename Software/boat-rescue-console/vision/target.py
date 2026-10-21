"""
落水目标检测：HSV 颜色分割 -> 水池坐标

取点策略：用轮廓的**底部中心点**作为目标点，而不是轮廓质心。
原因：目标浮在水面，水面接触点才是船需要抵达的位置；用质心会因水上部分
高度不同而上下漂移，尤其在目标靠近相机边缘时误差更大。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import config
from pool import pixel_to_pool

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False


@dataclass
class TargetPose:
    x: float
    y: float
    area_px: float
    bottom_px: tuple[int, int]


class TargetDetector:
    def __init__(self):
        if not HAS_CV2:
            raise RuntimeError("TargetDetector 需要 OpenCV，请先安装: pip install opencv-python")
        self._lost = 0
        self._last: TargetPose | None = None

    def _mask(self, frame_bgr) -> np.ndarray:
        hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
        mask = None
        for lo, hi in config.TARGET_HSV_RANGES:
            part = cv2.inRange(hsv, np.array(lo, dtype=np.uint8), np.array(hi, dtype=np.uint8))
            mask = part if mask is None else cv2.bitwise_or(mask, part)
        if mask is None:
            mask = np.zeros(hsv.shape[:2], dtype=np.uint8)

        # 形态学：先开后闭，去掉水面高光碎斑，再把目标内部空洞补上
        k = config.MORPH_KERNEL
        if k > 0:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        return mask

    def detect(self, frame_bgr, H) -> TargetPose | None:
        mask = self._mask(frame_bgr)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return self._lost_target()

        # 取面积最大的轮廓作为目标
        best = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(best)
        if area < config.MIN_TARGET_AREA_PX:
            return self._lost_target()

        # 底部中心点（水面接触点）
        x, y, w, h = cv2.boundingRect(best)
        bottom_px = (int(x + w / 2), int(y + h))
        px, py = pixel_to_pool(H, bottom_px)

        self._lost = 0
        self._last = TargetPose(x=px, y=py, area_px=area, bottom_px=bottom_px)
        return self._last

    def _lost_target(self) -> TargetPose | None:
        """连续丢失若干帧后才真正判丢；期间沿用上一次结果，避免坐标跳变。"""
        self._lost += 1
        if self._lost > config.TARGET_LOST_FRAMES:
            self._last = None
        return self._last
