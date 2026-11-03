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


def compute_homography(image_points: np.ndarray, pool_size: float = POOL_SIZE_M,
                       pool_width_m: float | None = None,
                       pool_height_m: float | None = None) -> np.ndarray:
    """
    由四个像素点计算单应性矩阵（像素 -> 米）。

    :param image_points: 形状 (4,2)，按 左下 -> 右下 -> 右上 -> 左上 的顺序
    :param pool_size: 正方形水池的边长（米）；给了 width/height 时忽略
    :param pool_width_m: 水池宽（X 方向，米）；默认等于 pool_size
    :param pool_height_m: 水池高（Y 方向，米）；默认等于 pool_size
    :return: 3x3 单应性矩阵

    说明：现场水池常常**不是正方形**（本项目沙盘池是圆角梯形）。四点单应
    只要求目标四边形的四个角，宽高可以不同；用同一个边长去映射非正方形池
    会让米坐标在一个方向整体缩放错，而且不会有任何报错 —— 所以这里允许
    分别给宽高。
    """
    if image_points.shape != (4, 2):
        raise ValueError(f"需要 4 个点，收到 {image_points.shape}")

    width = float(pool_width_m if pool_width_m is not None else pool_size)
    height = float(pool_height_m if pool_height_m is not None else pool_size)
    if width <= 0 or height <= 0:
        raise ValueError(f"水池宽高必须为正，收到 {width} x {height}")

    # 目标坐标系：左下为原点，X 向右，Y 向上
    dst = np.array(
        [
            [0.0, 0.0],
            [width, 0.0],
            [width, height],
            [0.0, height],
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


def save_calibration(H: np.ndarray, image_points: np.ndarray,
                     image_size: tuple[int, int] | None = None,
                     path: Path = CALIB_FILE,
                     pool_polygon_px: np.ndarray | None = None,
                     pool_width_m: float | None = None,
                     pool_height_m: float | None = None) -> None:
    """
    保存标定结果。

    :param image_size: 标定时的相机分辨率 (w, h)。**必须存**：单应矩阵是像素坐标
        的函数，换分辨率后同一组 H 会把米坐标整体缩放错，且不会有任何报错。
    """
    data = {
        "pool_size_m": POOL_SIZE_M,
        "image_points": np.asarray(image_points, dtype=np.float64).tolist(),
        "homography": np.asarray(H, dtype=np.float64).tolist(),
    }
    # 非矩形水池：把像素轮廓也存下来，运行期用于多边形内判定
    if pool_polygon_px is not None:
        poly = np.asarray(pool_polygon_px, dtype=np.float64).reshape(-1, 2)
        data["pool_polygon_px"] = poly.tolist()
        # 同时存米坐标版本，detector 直接用，避免运行期再算一遍
        try:
            data["pool_polygon_m"] = [list(map(float, pixel_to_pool(H, pt))) for pt in poly]
        except Exception:
            pass
    if pool_width_m is not None:
        data["pool_width_m"] = float(pool_width_m)
    if pool_height_m is not None:
        data["pool_height_m"] = float(pool_height_m)
    if image_size is not None:
        data["image_width"], data["image_height"] = int(image_size[0]), int(image_size[1])

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_calibration_info(path: Path = CALIB_FILE) -> dict:
    """读取标定文件，返回 {homography, image_width, image_height, ...}。"""
    if not path.exists():
        raise FileNotFoundError(
            f"未找到标定文件 {path.name}，请先运行: python locator.py --calibrate"
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    data["homography"] = np.array(data["homography"], dtype=np.float64)
    return data


def load_calibration(path: Path = CALIB_FILE) -> np.ndarray:
    """只取单应矩阵（老接口，保留向后兼容）。"""
    return load_calibration_info(path)["homography"]


def check_resolution(info: dict, width: int, height: int) -> str | None:
    """
    校验"标定分辨率"与"当前分辨率"是否一致。

    :return: 不一致时返回给用户看的错误文本；一致或旧标定文件（无尺寸字段）返回 None。
    """
    cw, ch = info.get("image_width"), info.get("image_height")
    if cw is None or ch is None:
        return None
    if int(cw) != int(width) or int(ch) != int(height):
        return (
            f"标定分辨率 {int(cw)}x{int(ch)} 与当前相机分辨率 {width}x{height} 不一致，"
            "坐标会整体缩放错。请用同一分辨率重新运行: python locator.py --calibrate"
        )
    return None


def calibrate_interactively(camera_index: int = 0,
                            width: int = 1920,
                            height: int = 1080) -> None:
    """打开相机，让用户点击水池四角，计算并保存标定结果。"""
    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        raise RuntimeError(f"无法打开相机 index={camera_index}")

    # 尽量取高分辨率，定位精度直接依赖像素密度。
    # 必须把**实际生效**的分辨率随 H 一起存下来：运行时如果相机给的是
    # 1280x720 而标定按 1920x1080 算，米坐标会整体缩放错且没有任何报错。
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"标定分辨率: 请求 {width}x{height}，实际 {actual_w}x{actual_h}")

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
            save_calibration(H, np.array(points, dtype=np.float32),
                             image_size=(actual_w, actual_h))
            print(f"标定完成，已保存到 {CALIB_FILE}（分辨率 {actual_w}x{actual_h}）")
            # 自检：把四角映射回去，应得到 (0,0) (L,0) (L,L) (0,L)
            for pt in points:
                print(f"    {pt} -> {pixel_to_pool(H, pt)}")
            break

    cap.release()
    cv2.destroyAllWindows()
