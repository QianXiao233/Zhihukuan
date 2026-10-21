"""
水池标定与坐标变换（单应性矩阵）

水池是平面，相机俯瞰，因此像素坐标 <-> 水池米坐标之间是**单应变换**（3x3 矩阵）。
标定方法：鼠标依次点击水池四个角，把像素坐标映射到 (0,0) (L,0) (L,L) (0,L)。
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:          # 允许在没有 OpenCV 的环境下做纯链路验证（--simulate）
    cv2 = None
    HAS_CV2 = False

# 水池实际边长（米）—— 标定与坐标量程都由它决定
POOL_SIZE_M = 1.2

CALIB_FILE = Path(__file__).with_name("calibration.json")


def _find_homography(src_px: np.ndarray, dst_m: np.ndarray) -> np.ndarray:
    """
    4 点单应性矩阵。有 OpenCV 时用 cv2.findHomography（带 RANSAC，更稳）；
    否则用纯 numpy 解 8x8 线性方程组（4 点恰好可解，无多余自由度）。
    """
    if HAS_CV2:
        H, _ = cv2.findHomography(src_px.astype(np.float32), dst_m.astype(np.float32))
        if H is None:
            raise RuntimeError("单应性矩阵计算失败，请检查四点是否共线或重合")
        return H

    # 构造 A h = b，其中 h = [h00 h01 h02 h10 h11 h12 h20 h21]^T, h22 = 1
    A = []
    b = []
    for (x, y), (u, v) in zip(src_px, dst_m):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        b.append(v)
    h, *_ = np.linalg.lstsq(np.array(A, dtype=np.float64),
                            np.array(b, dtype=np.float64), rcond=None)
    H = np.append(h, 1.0).reshape(3, 3)
    return H


def compute_homography(image_points: np.ndarray, pool_size: float = POOL_SIZE_M) -> np.ndarray:
    """
    由四个像素点计算单应性矩阵。

    :param image_points: 形状 (4,2)，按 左下 -> 右下 -> 右上 -> 左上 的顺序
    :param pool_size: 水池边长（米）
    :return: 3x3 单应性矩阵（像素 -> 米）
    """
    if image_points.shape != (4, 2):
        raise ValueError(f"需要 4 个点，收到 {image_points.shape}")

    # 目标坐标系：左下为原点，X 向右，Y 向上
    dst = np.array(
        [
            [0.0, 0.0],
            [pool_size, 0.0],
            [pool_size, pool_size],
            [0.0, pool_size],
        ],
        dtype=np.float64,
    )
    return _find_homography(image_points.astype(np.float64), dst)


def pixel_to_pool(H: np.ndarray, point_px) -> tuple[float, float]:
    """单个像素点 -> 水池米坐标（纯 numpy，不依赖 OpenCV）"""
    x, y = float(point_px[0]), float(point_px[1])
    w = H[2, 0] * x + H[2, 1] * y + H[2, 2]
    if abs(w) < 1e-12:
        return 0.0, 0.0
    px = (H[0, 0] * x + H[0, 1] * y + H[0, 2]) / w
    py = (H[1, 0] * x + H[1, 1] * y + H[1, 2]) / w
    return float(px), float(py)


def save_calibration(H: np.ndarray, image_points: np.ndarray, path: Path = CALIB_FILE) -> None:
    path.write_text(
        json.dumps(
            {
                "pool_size_m": POOL_SIZE_M,
                "image_points": image_points.tolist(),
                "homography": H.tolist(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def load_calibration(path: Path = CALIB_FILE) -> np.ndarray:
    if not path.exists():
        raise FileNotFoundError(
            f"未找到标定文件 {path.name}，请先运行: python locator.py --calibrate"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    return np.array(data["homography"], dtype=np.float64)


def calibrate_interactively(camera_index: int = 0) -> None:
    """打开相机，让用户点击水池四角，计算并保存标定结果。"""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开相机 index={camera_index}")

    # 尽量取高分辨率，定位精度直接依赖像素密度
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    points: list[tuple[int, int]] = []
    window = "calibrate - click 4 pool corners: BL, BR, TR, TL  (r=reset, q=quit)"

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))
            print(f"  已记录第 {len(points)} 点: ({x}, {y})")

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    print("请按顺序点击水池四角：左下 -> 右下 -> 右上 -> 左上")
    print("  r 键重置   q 键退出")

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        display = frame.copy()
        for i, pt in enumerate(points):
            cv2.circle(display, pt, 6, (0, 255, 255), -1)
            cv2.putText(display, str(i + 1), (pt[0] + 10, pt[1] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 255), 2)
        if len(points) >= 2:
            cv2.polylines(display, [np.array(points, dtype=np.int32)],
                          len(points) == 4, (0, 255, 0), 2)
        cv2.putText(display, f"points: {len(points)}/4", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.imshow(window, display)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            points.clear()
            print("  已重置")
        if len(points) == 4:
            H = compute_homography(np.array(points, dtype=np.float32))
            save_calibration(H, np.array(points, dtype=np.float32))
            print(f"标定完成，已保存到 {CALIB_FILE}")
            # 自检：把四角映射回去，应得到 (0,0) (L,0) (L,L) (0,L)
            for pt in points:
                print(f"    {pt} -> {pixel_to_pool(H, pt)}")
            break

    cap.release()
    cv2.destroyAllWindows()
