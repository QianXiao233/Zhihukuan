#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ArUco 码实时检测预览（贴码/调机位专用）。

为什么需要：船位靠船顶 ArUco 码，码贴不好（斜、小、反光、糊）时 locator.py
只会打印"未检测到船"，看不出到底哪里不行。本脚本把画面里**所有** ArUco 码
都找出来，并给出诊断：ID、像素边长、倾角、透视畸变程度、清晰度。

用法：
    python marker_probe.py                 # 0 号相机
    python marker_probe.py --camera 1
    python marker_probe.py --image shot.jpg  # 不开相机，直接测一张照片

看什么：
  - 绿框+ID     ：检出正常，位置可用
  - 灰框 "TOO SMALL"：码在画面里 < 35px，太远/太小
  - 灰框 "SKEW 62°"：码面太斜（>50°），应贴平
  - 灰框 "BLUR" ：模糊，无法稳定识别
  左上角会汇总：检出数、最好那个的边长/倾角

快捷键：q/ESC 退出，s 存帧，空格 暂停
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

DICT_NAME = "DICT_4X4_50"
MIN_SIDE_PX = 35.0          # 低于这个边长认为太远
MAX_SKEW_DEG = 50.0         # 倾角超过这个认为太斜


def get_dictionary(name: str):
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def side_lengths(quad: np.ndarray) -> list[float]:
    q = quad.reshape(4, 2)
    return [float(np.linalg.norm(q[i] - q[(i + 1) % 4])) for i in range(4)]


def skew_deg(quad: np.ndarray) -> float:
    """用相对两边的长度比估计倾斜程度：正对相机时对边长度接近。

    返回 0~90 度，0 = 正对，越大越斜。这是近似值：真实透视角度需要相机内参，
    但用于"贴平了没"的现场判断足够。
    """
    sides = side_lengths(quad)
    if min(sides) <= 1e-6:
        return 90.0
    # 对边比值：长边/短边 越大越斜
    horiz_ratio = max(sides[0], sides[2]) / max(1e-6, min(sides[0], sides[2]))
    vert_ratio = max(sides[1], sides[3]) / max(1e-6, min(sides[1], sides[3]))
    ratio = max(horiz_ratio, vert_ratio)
    # ratio=1 -> 0°，ratio=2 -> 约 60°，用 acos 近似
    return float(np.degrees(np.arccos(min(1.0, 1.0 / ratio))))


def sharpness(gray: np.ndarray, quad: np.ndarray) -> float:
    x, y, w, h = cv2.boundingRect(quad.reshape(-1, 2).astype(np.int32))
    x, y = max(0, x), max(0, y)
    patch = gray[y:y + h, x:x + w]
    if patch.size == 0:
        return 0.0
    return float(cv2.Laplacian(patch, cv2.CV_64F).var())


def analyze(frame: np.ndarray, detector) -> tuple[list[dict], np.ndarray]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gray)
    results = []
    vis = frame.copy()
    if ids is None or len(ids) == 0:
        return results, vis

    for quad, mid in zip(corners, ids.flatten()):
        q = quad.reshape(4, 2)
        sides = side_lengths(quad)
        side = float(np.mean(sides))
        skew = skew_deg(quad)
        sharp = sharpness(gray, quad)

        reasons = []
        if side < MIN_SIDE_PX:
            reasons.append(f"TOO SMALL {side:.0f}px")
        if skew > MAX_SKEW_DEG:
            reasons.append(f"SKEW {skew:.0f}deg")
        if sharp < 100:
            reasons.append(f"BLUR {sharp:.0f}")

        ok = not reasons
        colour = (0, 220, 0) if ok else (140, 140, 140)
        poly = q.astype(np.int32)
        cv2.polylines(vis, [poly], True, colour, 3)
        center = q.mean(axis=0).astype(int)
        label = f"ID{int(mid)} {side:.0f}px"
        cv2.putText(vis, label, (center[0] - 60, center[1] - 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, colour, 2, cv2.LINE_AA)
        if reasons:
            cv2.putText(vis, " ".join(reasons), (center[0] - 60, center[1] + 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 140, 255), 2, cv2.LINE_AA)

        results.append({
            "id": int(mid), "side_px": side, "skew_deg": skew,
            "sharpness": sharp, "ok": ok, "reasons": reasons,
        })
    return results, vis


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ArUco 码实时检测预览")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--image", default=None, help="只测一张图片（不开相机）")
    ap.add_argument("--dict", default=DICT_NAME, help=f"字典名（默认 {DICT_NAME}）")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    args = ap.parse_args(argv)

    try:
        dictionary = get_dictionary(args.dict)
    except AttributeError:
        print(f"[probe] 未知字典 {args.dict}", file=sys.stderr)
        return 2
    # 与 boat.py 使用**同一套放宽参数**，否则诊断看到的"稳不稳"和实跑不一致
    params = cv2.aruco.DetectorParameters()
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = 45
    params.adaptiveThreshWinSizeStep = 4
    params.adaptiveThreshConstant = 5.0
    params.minMarkerPerimeterRate = 0.008
    params.maxMarkerPerimeterRate = 4.0
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    params.cornerRefinementWinSize = 5
    params.cornerRefinementMaxIterations = 30
    params.cornerRefinementMinAccuracy = 0.05
    params.perspectiveRemovePixelPerCell = 8
    params.perspectiveRemoveIgnoredMarginPerCell = 0.2
    params.maxErroneousBitsInBorderRate = 0.5
    params.errorCorrectionRate = 0.8
    params.minCornerDistanceRate = 0.02
    params.minDistanceToBorder = 2
    params.minMarkerDistanceRate = 0.02
    detector = cv2.aruco.ArucoDetector(dictionary, params)

    # 单图模式
    if args.image:
        image = cv2.imread(str(Path(args.image)))
        if image is None:
            print(f"[probe] 读不到图片：{args.image}", file=sys.stderr)
            return 2
        results, vis = analyze(image, detector)
        print(f"[probe] {Path(args.image).name}: 检出 {len(results)} 个码")
        for r in results:
            status = "OK" if r["ok"] else " / ".join(r["reasons"])
            print(f"   ID{r['id']}  边长 {r['side_px']:.0f}px  倾角 {r['skew_deg']:.0f}°  "
                  f"清晰度 {r['sharpness']:.0f}  -> {status}")
        out = Path("marker_probe_result.jpg")
        cv2.imwrite(str(out), vis)
        print(f"[probe] 标注图：{out.resolve()}")
        return 0

    # 相机模式
    cap = None
    for backend in (cv2.CAP_MSMF, cv2.CAP_ANY, cv2.CAP_DSHOW):
        candidate = cv2.VideoCapture(args.camera, backend)
        if candidate.isOpened():
            candidate.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            ok, frame = candidate.read()
            if ok and frame is not None:
                cap = candidate
                print(f"[probe] 相机 {args.camera}: {frame.shape[1]}x{frame.shape[0]}")
                break
        candidate.release()
    if cap is None:
        print(f"[probe] 打不开相机 {args.camera}", file=sys.stderr)
        return 2

    print("[probe] 把码平贴到船顶，让它在画面里正对相机；q 退出，s 存帧")
    paused = False
    frame = None
    try:
        while True:
            if not paused:
                ok, frame = cap.read()
                if not ok or frame is None:
                    break
            results, vis = analyze(frame, detector)

            best = max(results, key=lambda r: r["side_px"]) if results else None
            if best is None:
                summary = "NO MARKER  (贴平？尺寸？光照？)"
                colour = (0, 0, 255)
            elif best["ok"]:
                summary = (f"OK  ID{best['id']}  {best['side_px']:.0f}px  "
                           f"skew {best['skew_deg']:.0f}deg  sharp {best['sharpness']:.0f}")
                colour = (0, 220, 0)
            else:
                summary = f"FOUND but {', '.join(best['reasons'])}"
                colour = (0, 165, 255)
            cv2.putText(vis, summary, (14, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, colour, 2, cv2.LINE_AA)
            cv2.putText(vis, f"{len(results)} marker(s)  q=quit  s=save  space=pause",
                        (14, vis.shape[0] - 16), cv2.FONT_HERSHEY_SIMPLEX,
                        0.6, (240, 240, 240), 1, cv2.LINE_AA)

            cv2.imshow("marker probe", vis)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = not paused
            if key == ord("s"):
                out = Path(f"marker_{len(results)}.jpg")
                cv2.imwrite(str(out), vis)
                print(f"[probe] 已保存 {out.resolve()}")
    finally:
        cap.release()
        cv2.destroyAllWindows()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
