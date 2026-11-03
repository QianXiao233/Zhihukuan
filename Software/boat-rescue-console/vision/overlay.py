#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把水池坐标系、检测结果、船位叠加到画面上（供 locator.py --show 使用）。

画什么：
  - 池壁轮廓（标定里的多边形，米坐标回投到像素）
  - 0.2 m 网格 + X/Y 数值，以及坐标轴箭头与原点标记
  - 目标检测框（红）+ 目标米坐标
  - 船位（蓝）+ 航向箭头
  - 左上角状态摘要（是否检测到船/目标、上报计数、FPS）

坐标系约定（与 pool.py / 船端一致）：
  X 向右、Y 向上，原点在标定时点的那四个角的「左下」。
  注意：图像坐标 y 向下，所以画网格时要用单应矩阵的逆把米坐标转回像素。
"""
from __future__ import annotations

import math
from typing import Iterable

import cv2
import numpy as np

# 配色（BGR）
COLOUR_POOL = (200, 200, 200)
COLOUR_GRID = (110, 110, 110)
COLOUR_AXIS_X = (60, 60, 230)
COLOUR_AXIS_Y = (230, 130, 60)
COLOUR_TARGET = (40, 40, 235)
COLOUR_BOAT = (235, 150, 40)
COLOUR_OK = (80, 200, 80)
COLOUR_WARN = (40, 170, 245)
COLOUR_BAD = (60, 60, 220)
FONT = cv2.FONT_HERSHEY_SIMPLEX


def _m2px(H_inv: np.ndarray, x: float, y: float) -> tuple[int, int] | None:
    v = H_inv @ np.array([x, y, 1.0], dtype=np.float64)
    if abs(v[2]) < 1e-12:
        return None
    px, py = v[0] / v[2], v[1] / v[2]
    if not (math.isfinite(px) and math.isfinite(py)):
        return None
    return int(round(px)), int(round(py))


def _label(frame, text, org, colour, scale=0.6, thickness=2, shadow=True):
    if shadow:
        cv2.putText(frame, text, (org[0] + 1, org[1] + 1), FONT, scale, (0, 0, 0), thickness + 2, cv2.LINE_AA)
    cv2.putText(frame, text, org, FONT, scale, colour, thickness, cv2.LINE_AA)


def draw_pool(frame: np.ndarray, H: np.ndarray, width_m: float, height_m: float,
              polygon_m: Iterable | None = None, grid_m: float = 0.2,
              draw_grid: bool = True) -> np.ndarray:
    """在 frame 上画池壁、网格与坐标轴（原地修改并返回）。"""
    H_inv = np.linalg.inv(H)

    # 池壁：优先用多边形，否则用矩形四角
    if polygon_m is not None and len(list(polygon_m)) >= 3:
        pts = [_m2px(H_inv, x, y) for x, y in polygon_m]
        pts = [p for p in pts if p is not None]
        if len(pts) >= 3:
            cv2.polylines(frame, [np.array(pts, np.int32)], True, COLOUR_POOL, 2, cv2.LINE_AA)
    else:
        corners = [(0, 0), (width_m, 0), (width_m, height_m), (0, height_m)]
        pts = [p for p in (_m2px(H_inv, x, y) for x, y in corners) if p is not None]
        if len(pts) == 4:
            cv2.polylines(frame, [np.array(pts, np.int32)], True, COLOUR_POOL, 2, cv2.LINE_AA)

    if not draw_grid:
        return frame

    # 网格
    nx = int(round(width_m / grid_m))
    ny = int(round(height_m / grid_m))
    for i in range(nx + 1):
        x = i * grid_m
        a, b = _m2px(H_inv, x, 0.0), _m2px(H_inv, x, height_m)
        if a and b:
            cv2.line(frame, a, b, COLOUR_GRID, 1, cv2.LINE_AA)
    for j in range(ny + 1):
        y = j * grid_m
        a, b = _m2px(H_inv, 0.0, y), _m2px(H_inv, width_m, y)
        if a and b:
            cv2.line(frame, a, b, COLOUR_GRID, 1, cv2.LINE_AA)

    # 坐标数值（沿两条边标注，避免糊在中间）
    for i in range(nx + 1):
        x = i * grid_m
        p = _m2px(H_inv, x, 0.0)
        if p:
            _label(frame, f"{x:.1f}", (p[0] - 12, p[1] + 18), COLOUR_AXIS_X, 0.45, 1)
    for j in range(ny + 1):
        y = j * grid_m
        p = _m2px(H_inv, 0.0, y)
        if p:
            _label(frame, f"{y:.1f}", (p[0] - 34, p[1] + 5), COLOUR_AXIS_Y, 0.45, 1)

    # 原点与坐标轴箭头
    origin = _m2px(H_inv, 0.0, 0.0)
    x_end = _m2px(H_inv, min(0.3, width_m * 0.3), 0.0)
    y_end = _m2px(H_inv, 0.0, min(0.3, height_m * 0.3))
    if origin:
        cv2.circle(frame, origin, 6, (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, origin, 6, (0, 0, 0), 1, cv2.LINE_AA)
        _label(frame, "(0,0)", (origin[0] + 8, origin[1] - 8), (255, 255, 255), 0.5, 1)
        if x_end:
            cv2.arrowedLine(frame, origin, x_end, COLOUR_AXIS_X, 3, cv2.LINE_AA, tipLength=0.25)
            _label(frame, "X+", (x_end[0] + 4, x_end[1] - 4), COLOUR_AXIS_X, 0.6, 2)
        if y_end:
            cv2.arrowedLine(frame, origin, y_end, COLOUR_AXIS_Y, 3, cv2.LINE_AA, tipLength=0.25)
            _label(frame, "Y+", (y_end[0] + 4, y_end[1] - 4), COLOUR_AXIS_Y, 0.6, 2)

    return frame


def draw_target(frame: np.ndarray, box_px: tuple[float, float, float, float] | None,
                metre: tuple[float, float] | None, confidence: float | None = None,
                source: str | None = None) -> np.ndarray:
    """画目标框与米坐标。box_px 为 (x1, y1, x2, y2)。"""
    if box_px is not None:
        x1, y1, x2, y2 = (int(round(v)) for v in box_px)
        cv2.rectangle(frame, (x1, y1), (x2, y2), COLOUR_TARGET, 3, cv2.LINE_AA)
        text = "TARGET"
        if confidence is not None:
            text += f" {confidence:.2f}"
        if source:
            text += f" ({source})"
        _label(frame, text, (x1, max(20, y1 - 8)), COLOUR_TARGET, 0.62, 2)
        if metre is not None:
            mx, my = metre
            # 在框中心画一个十字，明确"哪个点被当成目标位置"
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.drawMarker(frame, (cx, cy), COLOUR_TARGET, cv2.MARKER_CROSS, 18, 2, cv2.LINE_AA)
            _label(frame, f"({mx:.2f}, {my:.2f}) m",
                   (x1, min(frame.shape[0] - 8, y2 + 22)), COLOUR_TARGET, 0.62, 2)
    elif metre is not None:
        mx, my = metre
        _label(frame, f"target ({mx:.2f}, {my:.2f}) m", (16, 96), COLOUR_TARGET, 0.6, 2)
    return frame


def draw_boat(frame: np.ndarray, H_inv: np.ndarray, x: float, y: float,
              heading_deg: float | None) -> np.ndarray:
    """画船位与航向箭头（heading 单位度，0=+Y，顺时针为正）。"""
    p = _m2px(H_inv, x, y)
    if p is None:
        return frame
    cv2.circle(frame, p, 10, COLOUR_BOAT, -1, cv2.LINE_AA)
    cv2.circle(frame, p, 10, (255, 255, 255), 2, cv2.LINE_AA)
    if heading_deg is not None:
        rad = math.radians(heading_deg)
        dx, dy = math.sin(rad), math.cos(rad)      # 0°=+Y, 顺时针
        end = _m2px(H_inv, x + dx * 0.12, y + dy * 0.12)
        if end:
            cv2.arrowedLine(frame, p, end, COLOUR_BOAT, 3, cv2.LINE_AA, tipLength=0.3)
        _label(frame, f"BOAT {heading_deg:.0f}deg", (p[0] + 14, p[1] - 10), COLOUR_BOAT, 0.6, 2)
    else:
        _label(frame, f"BOAT ({x:.2f},{y:.2f})", (p[0] + 14, p[1] - 10), COLOUR_BOAT, 0.6, 2)
    return frame


def draw_status(frame: np.ndarray, lines: list[tuple[str, tuple[int, int, int]]],
                origin: tuple[int, int] = (14, 30), line_height: int = 26) -> np.ndarray:
    """左上角状态摘要。lines 为 [(文本, 颜色)]。"""
    x0, y0 = origin
    width = max((cv2.getTextSize(t, FONT, 0.62, 2)[0][0] for t, _ in lines), default=0) + 24
    height = line_height * len(lines) + 12
    overlay = frame.copy()
    cv2.rectangle(overlay, (x0 - 8, y0 - 22), (x0 + width, y0 - 22 + height), (24, 24, 24), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)
    for index, (text, colour) in enumerate(lines):
        _label(frame, text, (x0, y0 + index * line_height), colour, 0.62, 2, shadow=False)
    return frame


def render(frame: np.ndarray, H: np.ndarray, width_m: float, height_m: float,
           polygon_m=None, target_box_px=None, target_m=None, target_conf=None,
           target_source=None, boat: tuple[float, float, float | None] | None = None,
           status_lines: list[tuple[str, tuple[int, int, int]]] | None = None,
           draw_grid: bool = True) -> np.ndarray:
    """一次性画好全部叠加层（原地修改 frame 并返回）。"""
    H_inv = np.linalg.inv(H)
    draw_pool(frame, H, width_m, height_m, polygon_m, draw_grid=draw_grid)
    draw_target(frame, target_box_px, target_m, target_conf, target_source)
    if boat is not None:
        draw_boat(frame, H_inv, boat[0], boat[1], boat[2])
    if status_lines:
        draw_status(frame, status_lines)
    return frame

# ---------------------------------------------------------------------------
# 静态层缓存
#
# 池壁/网格/坐标轴/刻度这些**每帧都一样**的东西，每帧重算一次要 ~17 ms，
# 会把主循环压到 20 Hz 以下（实测 16.5 Hz），而服务端 400 ms 超时就会让船
# 反复"启动-待命"。这里把静态层渲染到一张 RGBA 图上缓存起来，每帧只做
# 一次 alpha 合成。
# ---------------------------------------------------------------------------

_STATIC_CACHE: dict[tuple, "np.ndarray"] = {}


def _static_key(H: "np.ndarray", width_m: float, height_m: float,
                polygon_m, shape: tuple[int, ...], grid_m: float) -> tuple:
    h = float(H[0, 0] + H[0, 1] * 3 + H[1, 0] * 7 + H[1, 1] * 11 + H[0, 2] * 13 + H[1, 2] * 17)
    poly_key = 0.0
    if polygon_m is not None:
        arr = np.asarray(polygon_m, dtype=np.float64).reshape(-1)
        poly_key = float(arr.sum()) if arr.size else 0.0
    return (round(h, 6), round(width_m, 4), round(height_m, 4),
            round(poly_key, 6), shape, round(grid_m, 4))


def _build_static(width: int, height: int, H: "np.ndarray", width_m: float,
                  height_m: float, polygon_m, grid_m: float) -> "np.ndarray":
    """把静态层画到独立 BGR 画布上，返回 (bgr, mask)。

    注意：不能直接在 BGRA 的视图上画 —— OpenCV 的 putText/line 对
    non-contiguous 视图会报 "Layout of the output array img is incompatible"。
    所以先画满一张 BGR，再用"非零像素"生成掩码。
    """
    bgr = np.zeros((height, width, 3), np.uint8)
    draw_pool(bgr, H, width_m, height_m, polygon_m, grid_m=grid_m)
    mask = bgr.any(axis=2)
    return bgr, mask


def render_fast(frame: "np.ndarray", H: "np.ndarray", width_m: float, height_m: float,
                polygon_m=None, target_box_px=None, target_m=None, target_conf=None,
                target_source=None, boat=None, status_lines=None,
                draw_grid: bool = True, grid_m: float = 0.2) -> "np.ndarray":
    """render 的缓存版：静态层只算一次，之后每帧只合成动态部分。

    坐标轴/网格在画面上是固定的，缓存后每帧开销从 ~17 ms 降到 <1 ms。
    """
    H_inv = np.linalg.inv(H)
    shape = frame.shape
    key = _static_key(H, width_m, height_m, polygon_m, shape, grid_m)
    cached = _STATIC_CACHE.get(key)
    if cached is None:
        cached = _build_static(shape[1], shape[0], H, width_m, height_m, polygon_m, grid_m)
        if len(_STATIC_CACHE) > 4:      # 换过几次标定后清一次，避免无限增长
            _STATIC_CACHE.clear()
        _STATIC_CACHE[key] = cached

    bgr, mask = cached
    frame[mask] = bgr[mask]

    draw_target(frame, target_box_px, target_m, target_conf, target_source)
    if boat is not None:
        draw_boat(frame, H_inv, boat[0], boat[1], boat[2])
    if status_lines:
        draw_status(frame, status_lines)
    return frame
