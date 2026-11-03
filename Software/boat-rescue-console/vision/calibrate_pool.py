#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
水池轮廓标定（支持不规则池形）。

为什么不用"点四个角"：四点单应假设水池是四边形。本项目的沙盘池左下明显外凸、
整体接近圆角梯形，用四个角框会**框不住凸出去的那部分水域**，落在框外的目标
会被 `_in_pool` 判成池外而丢弃。

做法：
  1. 沿池壁内沿**点一圈**（任意多个点，顺时针或逆时针都行）；
  2. 脚本自动用这圈点的**最小外接四边形**建立米坐标系（保证 X/Y 量程覆盖整个池子）；
  3. 池界判定用**你点的多边形**（`cv2.pointPolygonTest`），不规则形状完全贴合。

用法：
    python calibrate_pool.py --image shot.jpg      # 用照片标定（推荐，可反复重来）
    python calibrate_pool.py                       # 用相机实时画面

操作：
    - 左键沿池壁内沿依次点一圈（建议 8~24 个点，拐角和弧顶多点点）；
    - 点完按 Enter 结束采点；
    - 输入池子真实尺寸（长、宽，米）——用来把像素换算成米；
    - 检查网格与轮廓，Enter 保存 / r 重来。

快捷键：
    u   撤销上一个点
    r   全部重来
    q   退出不保存
    Enter 采点结束 / 确认保存
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pool as pool_mod  # noqa: E402

FONT = cv2.FONT_HERSHEY_SIMPLEX


def polygon_bbox_quad(polygon: np.ndarray) -> np.ndarray:
    """用多边形的最小外接四边形，作为米坐标系的四个基准角。

    返回顺序固定为 左下 -> 右下 -> 右上 -> 左上（图像坐标 y 向下）。
    用 minAreaRect 取最小外接矩形再排序——比"取凸包四个极值点"稳，
    因为不规则形状的极值点可能落在弧上。
    """
    pts = polygon.reshape(-1, 2).astype(np.float32)
    if len(pts) < 3:
        raise ValueError("至少需要 3 个点才能构成水池轮廓")

    rect = cv2.minAreaRect(pts)
    box = cv2.boxPoints(rect).astype(np.float32)
    order = np.argsort(box[:, 1])
    top = box[order[:2]]
    bottom = box[order[2:]]
    top = top[np.argsort(top[:, 0])]
    bottom = bottom[np.argsort(bottom[:, 0])]
    tl, tr = top[0], top[1]
    bl, br = bottom[0], bottom[1]
    return np.array([bl, br, tr, tl], dtype=np.float32)


class PolygonCalibrator:
    def __init__(self, image: np.ndarray, window: str = "calibrate pool"):
        self.base = image
        self.window = window
        self.points: list[tuple[int, int]] = []
        self.collecting = True
        cv2.namedWindow(window, cv2.WINDOW_NORMAL)
        cv2.setMouseCallback(window, self._on_mouse)

    def _on_mouse(self, event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN or not self.collecting:
            return
        self.points.append((x, y))
        if len(self.points) % 5 == 0 or len(self.points) <= 3:
            print(f"[calib] 第 {len(self.points)} 个点: ({x}, {y})")

    def _m2px(self, H_inv: np.ndarray, X: float, Y: float) -> tuple[int, int]:
        v = H_inv @ np.array([X, Y, 1.0])
        return int(round(v[0] / v[2])), int(round(v[1] / v[2]))

    def redraw(self, H: np.ndarray | None = None, width_m: float = 1.2,
               height_m: float = 1.0) -> np.ndarray:
        view = self.base.copy()

        if len(self.points) >= 2:
            pts = np.array(self.points, np.int32)
            closed = (not self.collecting) and len(self.points) >= 3
            cv2.polylines(view, [pts], closed, (0, 220, 0), 2, cv2.LINE_AA)
        for index, (x, y) in enumerate(self.points):
            cv2.circle(view, (x, y), 5, (0, 220, 0), -1, cv2.LINE_AA)
            cv2.circle(view, (x, y), 5, (255, 255, 255), 1, cv2.LINE_AA)
            if index < 10 or index % 5 == 0:
                cv2.putText(view, str(index + 1), (x + 7, y - 7), FONT, 0.5, (0, 255, 255), 1)

        if H is not None and len(self.points) >= 3:
            H_inv = np.linalg.inv(H)
            nx = max(1, int(round(width_m / 0.2)))
            ny = max(1, int(round(height_m / 0.2)))
            for i in range(nx + 1):
                X = width_m * i / nx
                a = self._m2px(H_inv, X, 0.0)
                b = self._m2px(H_inv, X, height_m)
                cv2.line(view, a, b, (105, 105, 105), 1, cv2.LINE_AA)
                cv2.putText(view, f"{X:.1f}", (a[0] - 12, a[1] + 16), FONT, 0.42, (60, 60, 230), 1)
            for j in range(ny + 1):
                Y = height_m * j / ny
                a = self._m2px(H_inv, 0.0, Y)
                b = self._m2px(H_inv, width_m, Y)
                cv2.line(view, a, b, (105, 105, 105), 1, cv2.LINE_AA)
                cv2.putText(view, f"{Y:.1f}", (a[0] - 32, a[1] + 4), FONT, 0.42, (230, 130, 60), 1)

            origin = self._m2px(H_inv, 0.0, 0.0)
            xe = self._m2px(H_inv, min(0.25, width_m * 0.25), 0.0)
            ye = self._m2px(H_inv, 0.0, min(0.25, height_m * 0.25))
            cv2.circle(view, origin, 7, (255, 255, 255), -1, cv2.LINE_AA)
            cv2.arrowedLine(view, origin, xe, (60, 60, 230), 3, cv2.LINE_AA, tipLength=0.25)
            cv2.arrowedLine(view, origin, ye, (230, 130, 60), 3, cv2.LINE_AA, tipLength=0.25)
            cv2.putText(view, "X+", (xe[0] + 4, xe[1] - 4), FONT, 0.55, (60, 60, 230), 2)
            cv2.putText(view, "Y+", (ye[0] + 4, ye[1] - 4), FONT, 0.55, (230, 130, 60), 2)

            quad = polygon_bbox_quad(np.array(self.points, np.float32))
            cv2.polylines(view, [quad.astype(np.int32)], True, (200, 120, 255), 1, cv2.LINE_AA)

        if self.collecting:
            hint = (f"click along pool wall: {len(self.points)} pts   "
                    f"Enter=finish  u=undo  r=reset  q=quit")
            colour = (0, 220, 255)
        else:
            hint = (f"{len(self.points)} pts  {width_m:.2f} x {height_m:.2f} m   "
                    f"Enter=save  u=undo  r=reset  q=quit")
            colour = (0, 220, 0)
        cv2.rectangle(view, (0, 0), (view.shape[1], 40), (26, 26, 26), -1)
        cv2.putText(view, hint, (12, 27), FONT, 0.68, colour, 2, cv2.LINE_AA)
        return view

    def run(self, width_m: float, height_m: float):
        while True:
            H = quad = None
            if not self.collecting and len(self.points) >= 3:
                try:
                    quad = polygon_bbox_quad(np.array(self.points, np.float32))
                    H = pool_mod.compute_homography(quad, pool_width_m=width_m,
                                                    pool_height_m=height_m)
                except Exception as exc:      # noqa: BLE001
                    print(f"[calib] 无法生成标定：{exc}", file=sys.stderr)
                    H = None
            cv2.imshow(self.window, self.redraw(H, width_m, height_m))
            key = cv2.waitKey(20) & 0xFF
            if key in (ord("q"), 27):
                cv2.destroyWindow(self.window)
                return None
            if key == ord("u") and self.points:
                self.points.pop()
                print("[calib] 撤销一个点")
            if key == ord("r"):
                self.points.clear()
                self.collecting = True
                print("[calib] 重来")
            if key in (13, 10):
                if self.collecting:
                    if len(self.points) < 3:
                        print("[calib] 至少需要 3 个点", file=sys.stderr)
                        continue
                    self.collecting = False
                    print(f"[calib] 采点结束（{len(self.points)} 点）；检查网格后按 Enter 保存")
                else:
                    if H is None or quad is None:
                        print("[calib] 标定无效，请重来", file=sys.stderr)
                        continue
                    cv2.destroyWindow(self.window)
                    return quad, np.array(self.points, np.float32), width_m, height_m


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="水池轮廓标定（支持不规则池形）")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--image", default=None, help="用一张照片标定（推荐）")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--pool-width", type=float, default=None, help="池壁内沿长（米）")
    ap.add_argument("--pool-height", type=float, default=None, help="池壁内沿宽（米）")
    ap.add_argument("--out", default=None, help="输出路径（默认 calibration.json）")
    args = ap.parse_args(argv)

    if args.image:
        image = cv2.imread(str(Path(args.image)))
        if image is None:
            print(f"[calib] 读不到图片：{args.image}", file=sys.stderr)
            return 2
        print(f"[calib] 图片：{args.image}  ({image.shape[1]}x{image.shape[0]})")
        cap = None
    else:
        cap = None
        for backend in (cv2.CAP_MSMF, cv2.CAP_ANY, cv2.CAP_DSHOW):
            candidate = cv2.VideoCapture(args.camera, backend)
            if candidate.isOpened():
                candidate.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
                candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
                ok, frame = candidate.read()
                if ok and frame is not None:
                    cap, image = candidate, frame
                    print(f"[calib] 相机 {args.camera}: {frame.shape[1]}x{frame.shape[0]}")
                    break
            candidate.release()
        if cap is None:
            print(f"[calib] 打不开相机 {args.camera}", file=sys.stderr)
            return 2

    width_m, height_m = args.pool_width, args.pool_height
    if width_m is None or height_m is None:
        print("\n[calib] 输入池子真实尺寸（池壁内沿，米）；回车用估算值 1.2 x 1.0")
        try:
            raw = input("  长（X 方向）: ").strip()
            width_m = float(raw) if raw else 1.2
            raw = input("  宽（Y 方向）: ").strip()
            height_m = float(raw) if raw else 1.0
        except (EOFError, ValueError):
            width_m, height_m = 1.2, 1.0
            print("  （输入无效，用 1.2 x 1.0）")
    print(f"[calib] 池子尺寸：{width_m} x {height_m} m")

    cal = PolygonCalibrator(image)
    print("\n[calib] 沿池壁内沿点一圈（建议 8~24 个点，拐角/弧顶多点点）")
    print("[calib] 点完按 Enter，再按 Enter 保存；u=撤销 r=重来 q=退出")
    result = cal.run(width_m, height_m)
    if cap is not None:
        cap.release()
    if result is None:
        print("[calib] 已取消，未保存")
        return 1

    quad, polygon_px, width_m, height_m = result
    H = pool_mod.compute_homography(quad, pool_width_m=width_m, pool_height_m=height_m)
    out_path = Path(args.out) if args.out else pool_mod.CALIB_FILE
    pool_mod.save_calibration(
        H, quad, image_size=(image.shape[1], image.shape[0]),
        path=out_path, pool_width_m=width_m, pool_height_m=height_m,
        pool_polygon_px=polygon_px,
    )
    print(f"\n[calib] 已保存：{out_path}")
    print(f"[calib] 轮廓点：{len(polygon_px)} 个")
    print(f"[calib] 外接四边形（px）：{[[int(v) for v in p] for p in quad]}")
    print(f"[calib] 尺寸：{width_m} x {height_m} m")
    print("[calib] 下一步：python locator.py --show（看网格与轮廓是否贴合池壁）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
