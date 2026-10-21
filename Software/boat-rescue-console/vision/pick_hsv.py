"""
HSV 取色工具 —— 现场测目标颜色

用法：
    python pick_hsv.py

操作：
    - 把目标（橙色浮球等）放在画面里
    - 鼠标移到目标上，窗口左上会实时显示该点的 HSV
    - **左键点击**会把该点周围 5x5 的 HSV 范围打印到控制台
    - 记下 H/S/V 的大致上下界，填进 config.py 的 TARGET_HSV_RANGES
    - 按 q 退出

为什么必须实测：
    相机白平衡、灯光色温、水面反光都会显著改变 HSV。同一套阈值换一个房间
    或换一个时段（自然光）就可能完全失效。
"""
from __future__ import annotations

import cv2
import numpy as np

import config

# 点击时取样的邻域半径
SAMPLE_RADIUS = 2


def main() -> None:
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    if not cap.isOpened():
        raise SystemExit(f"无法打开相机 index={config.CAMERA_INDEX}")

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.CAMERA_FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)

    state = {"hsv": (0, 0, 0), "samples": []}
    window = "pick_hsv - move to read, LEFT CLICK to sample, q to quit"

    def on_mouse(event, x, y, _flags, _param):
        if event == cv2.EVENT_MOUSEMOVE:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            state["hsv"] = tuple(int(v) for v in hsv[y, x])
        elif event == cv2.EVENT_LBUTTONDOWN:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            y0, y1 = max(0, y - SAMPLE_RADIUS), min(hsv.shape[0], y + SAMPLE_RADIUS + 1)
            x0, x1 = max(0, x - SAMPLE_RADIUS), min(hsv.shape[1], x + SAMPLE_RADIUS + 1)
            patch = hsv[y0:y1, x0:x1].reshape(-1, 3)
            h_min, s_min, v_min = patch.min(axis=0)
            h_max, s_max, v_max = patch.max(axis=0)
            state["samples"].append((int(h_min), int(s_min), int(v_min),
                                     int(h_max), int(s_max), int(v_max)))
            print(f"[采样 {len(state['samples'])}] 像素({x},{y}) HSV 范围: "
                  f"H {h_min}-{h_max}  S {s_min}-{s_max}  V {v_min}-{v_max}")
            print(f"    -> 可填: (({int(h_min)}, {int(s_min)}, {int(v_min)}), "
                  f"({int(h_max)}, {int(s_max)}, {int(v_max)}))")

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    print("把目标放在画面中，左键点击取样。按 q 退出。")
    print("提示：多点几个位置（目标亮处/暗处），取并集更稳。")

    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        h, s, v = state["hsv"]
        cv2.putText(frame, f"HSV = {h}, {s}, {v}", (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(frame, f"samples: {len(state['samples'])}", (20, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        cv2.imshow(window, frame)
        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

    if state["samples"]:
        print("\n所有采样点汇总（取并集填入 config.py）：")
        arr = np.array(state["samples"])
        print(f"    (({arr[:,0].min()}, {arr[:,1].min()}, {arr[:,2].min()}), "
              f"({arr[:,3].max()}, {arr[:,4].max()}, {arr[:,5].max()}))")


if __name__ == "__main__":
    main()
