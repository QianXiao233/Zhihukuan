"""航向算法的数值回归测试（不需要相机、不需要 OpenCV）。

背景：曾经用 x+y / y-x 把 ArUco 的四个角"按图像坐标重排"，等价于假设
码在画面里基本是正的。码一旦转过 45°，角的物理身份就被认错，航向会在
大半圈上跳 90°/180°，船端 PID 于是绕着目标转圈。

本测试用纯几何方式复现这个失效模式，并验证现在的实现（直接使用检测器
返回的、随码旋转的原始角点顺序）在整个 360° 上连续。

运行：
    cd Software/boat-rescue-console/vision
    python test_boat_heading.py
"""
from __future__ import annotations

import math

import numpy as np

import boat
import pool

# ---- 模拟像素 -> 水池米的单应矩阵（1.2 m 水池 / 800 px，Y 轴翻转）----
SCALE = 1.2 / 800.0
POOL_CENTER = np.array([0.6, 0.6])
H = np.array([[SCALE, 0.0, 0.0], [0.0, -SCALE, 1.2], [0.0, 0.0, 1.0]])

# ---- 5cm 码在自身坐标系下的 tl/tr/br/bl（y 向上）----
A = 0.025
CANON_M = np.array([[-A, A], [A, A], [A, -A], [-A, -A]], dtype=np.float64)


def pool_to_px(points_m: np.ndarray) -> np.ndarray:
    """水池米坐标 -> 像素坐标（H 的逆变换）。"""
    px = points_m[..., 0] / SCALE
    py = (1.2 - points_m[..., 1]) / SCALE
    return np.stack([px, py], axis=-1)


def marker_quad(theta_deg: float) -> np.ndarray:
    """把码绕自身中心逆时针转 theta，摆到水池中心，返回像素四角。"""
    rad = math.radians(theta_deg)
    rot = np.array([[math.cos(rad), -math.sin(rad)],
                    [math.sin(rad), math.cos(rad)]])
    return pool_to_px((rot @ CANON_M.T).T + POOL_CENTER)


def old_order_corners(corners: np.ndarray) -> np.ndarray:
    """被删除的旧实现，仅用于对照证明它确实会错（勿在正式代码中使用）。"""
    pts = np.asarray(corners, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).reshape(-1)          # y - x
    return np.array([
        pts[np.argmin(s)], pts[np.argmin(d)],
        pts[np.argmax(s)], pts[np.argmax(d)],
    ], dtype=np.float32)


def angle_diff(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


def main() -> None:
    # 1) 单应矩阵自检：码中心应正好落在水池中心
    center_m = pool.pixel_to_pool(H, pool_to_px(POOL_CENTER))
    assert abs(center_m[0] - POOL_CENTER[0]) < 1e-9 and abs(center_m[1] - POOL_CENTER[1]) < 1e-9, center_m

    # 2) canonical_corners 必须保持原顺序，不能排序
    raw = marker_quad(37.0).astype(np.float32).reshape(1, 4, 2)
    assert np.array_equal(boat.canonical_corners(raw), raw.reshape(4, 2)), \
        "canonical_corners 不能改变角点顺序"

    # 3) 航向随旋转连续变化：heading(theta) - heading(0) 应等于 -theta
    base = boat.heading_from_corners(boat.canonical_corners(marker_quad(0.0)), H)
    worst = 0.0
    for theta in range(0, 360, 5):
        quad = boat.canonical_corners(marker_quad(theta))
        got = boat.heading_from_corners(quad, H)
        err = angle_diff(got, (base - theta) % 360.0)
        worst = max(worst, abs(err))
        assert abs(err) < 0.05, f"theta={theta}° 航向误差 {err:.2f}°"
    print(f"[OK] 新实现：0~355° 全程连续，最大误差 {worst:.3f}°")

    # 4) 对照：旧实现只在一个 90° 扇区内正确（这正是被修掉的 bug）
    failures = []
    for theta in range(0, 360, 5):
        quad = marker_quad(theta)
        good = boat.heading_from_corners(boat.canonical_corners(quad), H)
        bad = boat.heading_from_corners(old_order_corners(quad), H)
        if abs(angle_diff(bad, good)) > 1.0:
            failures.append(theta)
    assert failures, "旧实现居然没出错？测试本身可能失效了"
    print(f"[OK] 旧实现（按图像重排）在 {len(failures)}/{len(range(0,360,5))} 个朝向上错误，"
          f"例如 {failures[:3]}°，误差可达 90°/180° —— 回归已被本测试覆盖")

    print("test_boat_heading.py: 全部断言通过")


if __name__ == "__main__":
    main()
