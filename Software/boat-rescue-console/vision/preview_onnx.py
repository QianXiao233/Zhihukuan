#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相机 + ONNX 模型实时预览（不需要水池标定）。

用途：刚训练出模型时，先直观确认"能不能在实时画面上框住目标"，
不依赖 pool.py 的单应标定（locator.py --show 必须先标定四个池角）。

用法：
    python preview_onnx.py                        # 用 config 里的模型和 0 号相机
    python preview_onnx.py --camera 1             # 换相机
    python preview_onnx.py --onnx path\\best.onnx  # 换模型
    python preview_onnx.py --conf 0.4 --record    # 提高阈值 / 录一段

快捷键：
    q / ESC  退出
    s        保存当前帧（带框）
    空格     暂停/继续（暂停时仍显示最后一帧，方便看细节）
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2
import numpy as np


def letterbox(image: np.ndarray, size: int):
    h, w = image.shape[:2]
    ratio = min(size / w, size / h)
    new_w, new_h = int(round(w * ratio)), int(round(h * ratio))
    resized = cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((size, size, 3), 114, np.uint8)
    pad_x, pad_y = (size - new_w) // 2, (size - new_h) // 2
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    return canvas, ratio, pad_x, pad_y


def decode(output: np.ndarray, conf: float, iou: float, single_class: bool = True):
    pred = np.asarray(output, dtype=np.float32)
    if pred.ndim == 3:
        pred = pred[0]
    # (1, 4+nc, N) 或 (1, N, 4+nc)
    if pred.shape[0] < pred.shape[1] and pred.shape[0] <= 256:
        pred = pred.T
    boxes, class_scores = pred[:, :4], pred[:, 4:]
    if class_scores.shape[1] == 1:
        scores = class_scores[:, 0]
    else:
        scores = class_scores.max(axis=1)
    keep = scores >= conf
    if not keep.any():
        return []
    xywh = []
    for cx, cy, w, h in boxes[keep]:
        xywh.append([float(cx - w / 2), float(cy - h / 2), float(w), float(h)])
    confs = [float(s) for s in scores[keep]]
    idx = cv2.dnn.NMSBoxes(xywh, confs, 0.0, iou)
    if len(idx) == 0:
        return []
    out = []
    for i in np.array(idx).reshape(-1):
        x, y, w, h = xywh[int(i)]
        out.append((x, y, w, h, confs[int(i)]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="相机 + ONNX 实时预览（免标定）")
    ap.add_argument("--onnx", default=None, help="模型路径（默认取 config.YOLO_MODEL）")
    ap.add_argument("--camera", type=int, default=0, help="相机索引（默认 0）")
    ap.add_argument("--imgsz", type=int, default=None, help="输入尺寸（默认 config.YOLO_INPUT_SIZE，或读模型）")
    ap.add_argument("--conf", type=float, default=0.35, help="置信度阈值（默认 0.35）")
    ap.add_argument("--iou", type=float, default=0.45, help="NMS IoU（默认 0.45）")
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument("--record", default=None, help="录制成 mp4（给路径）")
    ap.add_argument("--every", type=int, default=1, help="每 N 帧推理一次（默认 1）")
    args = ap.parse_args(argv)

    # 默认从 config 取，保证和正式流程一致
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import config  # type: ignore

        onnx_path = Path(args.onnx or config.YOLO_MODEL or "")
        imgsz = args.imgsz or getattr(config, "YOLO_INPUT_SIZE", 640)
    except Exception:
        onnx_path = Path(args.onnx or "")
        imgsz = args.imgsz or 640

    if not onnx_path.is_file():
        print(f"[preview] 找不到模型：{onnx_path}", file=sys.stderr)
        print("[preview] 用 --onnx 指定，或先改 config.YOLO_MODEL", file=sys.stderr)
        return 2

    net = cv2.dnn.readNetFromONNX(str(onnx_path))
    print(f"[preview] 模型：{onnx_path.name}  输入 {imgsz}  conf>={args.conf}")

    cap = None
    for backend in (cv2.CAP_MSMF, cv2.CAP_ANY, cv2.CAP_DSHOW):
        candidate = cv2.VideoCapture(args.camera, backend)
        if candidate.isOpened():
            candidate.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
            candidate.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
            ok, frame = candidate.read()
            if ok and frame is not None:
                cap = candidate
                print(f"[preview] 相机 {args.camera}：{frame.shape[1]}x{frame.shape[0]}")
                break
        candidate.release()
    if cap is None:
        print(f"[preview] 打不开相机 {args.camera}", file=sys.stderr)
        return 2

    writer = None
    paused = False
    last_boxes = []
    frame_index = 0
    fps = 0.0
    t_last = time.time()
    win = "preview - q=quit  s=save  space=pause"

    try:
        while True:
            if not paused:
                ok, frame = cap.read()
                if not ok or frame is None:
                    print("[preview] 读帧失败，退出", file=sys.stderr)
                    break
                h0, w0 = frame.shape[:2]

                if frame_index % max(1, args.every) == 0:
                    padded, ratio, pad_x, pad_y = letterbox(frame, imgsz)
                    blob = cv2.dnn.blobFromImage(padded, 1 / 255.0, (imgsz, imgsz), swapRB=True, crop=False)
                    net.setInput(blob)
                    pred = net.forward()
                    dets = decode(pred, args.conf, args.iou)
                    inv = 1.0 / max(1e-9, ratio)
                    last_boxes = []
                    for x, y, w, h, conf in dets:
                        X1 = (x - pad_x) * inv
                        Y1 = (y - pad_y) * inv
                        X2 = (x + w - pad_x) * inv
                        Y2 = (y + h - pad_y) * inv
                        last_boxes.append((max(0, X1), max(0, Y1), min(w0 - 1, X2), min(h0 - 1, Y2), conf))
                frame_index += 1

            view = frame.copy()
            for x1, y1, x2, y2, conf in last_boxes:
                cv2.rectangle(view, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 3)
                cv2.putText(view, f"{conf:.2f}", (int(x1), max(22, int(y1) - 8)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2, cv2.LINE_AA)

            now = time.time()
            if now - t_last >= 0.5:
                fps = frame_index / (now - t_last) if now > t_last else 0
                t_last, frame_index = now, 0
            cv2.putText(view, f"{len(last_boxes)} target(s)  {fps:.1f} fps  conf>={args.conf}",
                        (14, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.85,
                        (0, 255, 0) if last_boxes else (180, 180, 180), 2, cv2.LINE_AA)

            cv2.imshow(win, view)
            if writer is not None:
                writer.write(view)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if key == ord(" "):
                paused = not paused
                print(f"[preview] {'暂停' if paused else '继续'}")
            if key == ord("s"):
                out = Path(f"preview_{int(time.time())}.jpg")
                cv2.imwrite(str(out), view)
                print(f"[preview] 已保存 {out}")
    finally:
        cap.release()
        if writer is not None:
            writer.release()
        cv2.destroyAllWindows()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
