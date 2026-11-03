"""
detector.py 的自包含回归测试（不需要相机、不需要真实模型）。

全部用 cv2 合成帧：水面背景（渐变 + 噪声 + 低饱和高光 + 橙色小噪点）+ 橙色椭圆目标
（带白色高光）+ 池外橙色大块，靠一个真实的透视单应矩阵 H 把水池米坐标和像素互相映射，
因此跑到的就是现场那条代码路径：H 的逆 -> ROI -> 多边形掩膜 -> HSV -> 形态学 -> 轮廓
打分 -> 跟踪 -> 输出米坐标。

覆盖的断言：
  1. H 与水池几何自检（四角、往返变换）
  2. 池内目标：检出、米坐标与"轮廓底边中点"一致、面积换算正确、source=classical
  3. 池外目标：完全在池外的大块橙色被拒（包括落在外接矩形斜角、且比池内目标更大的情况）
  4. 无目标：返回 None
  5. 形状异常：细长反光条（填充率低）、过小噪点被拒
  6. 多段 / 自定义 HSV：显式单段时红色不检，默认多段时红色可检
  7. 跟踪：连续帧 track_id 稳定、坐标平滑、速度估计方向与量级正确
  8. 短暂遮挡后重捕：track_id 保持
  9. 丢失：confidence 逐帧衰减、坐标不漂移、超过 lost_frames 后返回 None
 10. YOLOv8 输出解码（1x84xN + 1x5xN 两种形态、类别过滤、阈值）
 11. letterbox 几何
 12. 融合策略：人形高置信优先 / 低置信让位给传统 / 池外人形被拒（用 FakeNet 注入，
     不需要真模型）
 13. 真实 ONNX 模型存在时能加载并推理（模型缺失则打印 SKIP）
 14. 1080P 单帧耗时（打印实测值）

运行（在 vision 目录下）：
    D:\\miniconda3\\python.exe test_detector.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import detector as det_mod            # noqa: E402
import pool                           # noqa: E402
from pool import pixel_to_pool        # noqa: E402

# ---------------------------------------------------------------------------
# 合成场景的几何：1280x960 画面 + 一个透视梯形水池（远端窄、近端宽）
#   pool.compute_homography 的角点顺序是：左下 -> 右下 -> 右上 -> 左上
# ---------------------------------------------------------------------------
W, H = 1280, 960
POOL_QUAD = np.array(
    [[150.0, 900.0], [1150.0, 900.0], [1000.0, 300.0], [300.0, 300.0]],
    dtype=np.float32,
)
H_MAT = pool.compute_homography(POOL_QUAD)
POOL_M = 1.2

ORANGE = (0, 140, 255)          # BGR：典型浮球橙
WATER = (122, 130, 128)

TOL_M = 0.02                    # 米坐标容差


# ---------------------------------------------------------------------------
# 场景合成工具
# ---------------------------------------------------------------------------
def px(points_m) -> np.ndarray:
    """水池米坐标 -> 像素坐标（用 H 的逆）。"""
    pts = np.asarray(points_m, dtype=np.float64).reshape(-1, 2)
    homog = np.hstack([pts, np.ones((pts.shape[0], 1))])
    Hinv = np.linalg.inv(H_MAT)
    mapped = homog @ Hinv.T
    mapped = mapped[:, :2] / mapped[:, 2:3]
    return mapped


def px1(point_m) -> tuple[float, float]:
    x, y = px([point_m])[0]
    return float(x), float(y)


def make_water(rng: np.random.Generator, w: int = W, h: int = H) -> np.ndarray:
    """水面背景：竖向渐变 + 高斯噪声 + 低饱和高光/波纹（都要落在 HSV 橙色段之外）。"""
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]     # (h,1) 广播到 (h,w)
    base = np.empty((h, w, 3), dtype=np.float32)
    base[..., 0] = WATER[0] + 18.0 * yy
    base[..., 1] = WATER[1] + 16.0 * yy
    base[..., 2] = WATER[2] + 14.0 * yy
    base += rng.normal(0.0, 3.0, size=base.shape).astype(np.float32)
    img = np.clip(base, 0, 255).astype(np.uint8)

    # 波纹：略亮的偏蓝灰，饱和度仍然很低
    for _ in range(14):
        cx = int(rng.integers(0, w))
        cy = int(rng.integers(0, h))
        axes = (int(rng.integers(30, 120)), int(rng.integers(10, 40)))
        cv2.ellipse(img, (cx, cy), axes, float(rng.uniform(0, 180)), 0, 360, (152, 161, 158), 2)

    # 镜面高光：白 -> S≈0，HSV 的 S 下限会挡掉（这条比形态学更可靠）
    for _ in range(25):
        cx = int(rng.integers(0, w))
        cy = int(rng.integers(0, h))
        cv2.circle(img, (cx, cy), int(rng.integers(1, 6)), (246, 250, 248), -1)

    # 橙色小噪点：单点面积远小于 MIN_TARGET_AREA_PX，应被面积/形态学拒掉
    for _ in range(12):
        cx = int(rng.integers(20, w - 20))
        cy = int(rng.integers(20, h - 20))
        cv2.circle(img, (cx, cy), int(rng.integers(1, 3)), ORANGE, -1)
    return img


def draw_buoy(img: np.ndarray, center_m, radius_m: float = 0.05,
              color=ORANGE) -> tuple[float, float]:
    """
    在池内画一个橙色浮球（透视椭圆），返回它**轮廓底边中点**对应的水池米坐标。

    为什么返回底边而不是圆心：检测器（和 target.py 一样）取轮廓 bbox 的底边中点作为
    水面接触点，因此检出坐标会比圆心低一个半径——这是设计行为，测试要按它断言。
    """
    cx, cy = px1(center_m)
    rx, _ = px1((center_m[0] + radius_m, center_m[1]))
    _, ry = px1((center_m[0], center_m[1] + radius_m))
    ax = max(3, int(round(abs(rx - cx))))
    ay = max(3, int(round(abs(ry - cy))))
    center = (int(round(cx)), int(round(cy)))
    cv2.ellipse(img, center, (ax, ay), 0, 0, 360, color, -1)
    # 白色高光：低饱和 -> 被 HSV 挡掉，形成目标内部的小洞（闭运算补洞）
    cv2.circle(img, (center[0] - ax // 3, center[1] - ay // 3),
               max(2, min(ax, ay) // 8), (250, 250, 250), -1)
    return pixel_to_pool(H_MAT, (center[0], center[1] + ay))


def draw_blob_px(img: np.ndarray, center_px, radius_px: int, color=ORANGE) -> None:
    cv2.circle(img, (int(center_px[0]), int(center_px[1])), int(radius_px), color, -1)


def frame_with(buoy_m=(0.6, 0.6), radius_m: float = 0.05, seed: int = 0):
    img = make_water(np.random.default_rng(seed))
    expected = draw_buoy(img, buoy_m, radius_m)
    return img, expected


def close_to(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol


# ---------------------------------------------------------------------------
# 1. 几何自检
# ---------------------------------------------------------------------------
def test_geometry() -> None:
    corners_m = [(0.0, 0.0), (POOL_M, 0.0), (POOL_M, POOL_M), (0.0, POOL_M)]
    pix = px(corners_m)
    # 标定输入的四个像素点 -> 米坐标，必须正好是 (0,0)(1.2,0)(1.2,1.2)(0,1.2)
    for corner_px, want_m in zip(POOL_QUAD, corners_m):
        back = pixel_to_pool(H_MAT, corner_px)
        assert close_to(back[0], want_m[0], 1e-6) and close_to(back[1], want_m[1], 1e-6), (back, want_m)
    # 米坐标 -> 像素（H 的逆）应与标定输入一致（顺序 BL,BR,TR,TL）
    # 容差 1e-3 px：H 求逆会有 ~1e-4 px 的浮点误差
    for got, want in zip(pix, POOL_QUAD):
        assert close_to(got[0], want[0], 1e-3) and close_to(got[1], want[1], 1e-3), (got, want)

    # 池心、池外各点的往返一致性
    for m in [(0.0, 0.0), (1.2, 1.2), (0.6, 0.6), (0.1, 1.1)]:
        back = pixel_to_pool(H_MAT, px1(m))
        assert close_to(back[0], m[0], 1e-6) and close_to(back[1], m[1], 1e-6)
    print("[OK] 1 几何：H 四角映射与往返变换一致")


# ---------------------------------------------------------------------------
# 2. 池内目标检出
# ---------------------------------------------------------------------------
def test_detect_in_pool() -> None:
    det = det_mod.Detector(yolo_enabled=False)
    frame, expected = frame_with((0.6, 0.6))
    result = det.detect(frame, H_MAT)
    assert result is not None, "池内橙色浮球没有被检出"
    assert result.source == "classical", result.source
    assert result.track_id == 1, result.track_id
    assert 0.0 < result.confidence <= 1.0, result.confidence
    assert result.confidence > 0.5, f"置信度偏低: {result.confidence}"
    assert close_to(result.x, expected[0], TOL_M), (result.x, expected[0])
    assert close_to(result.y, expected[1], TOL_M), (result.y, expected[1])
    assert isinstance(result.bottom_px, tuple) and len(result.bottom_px) == 2

    # 面积换算：应约等于椭圆面积 pi*a*b（ROI 降采样后要能还原到全分辨率）
    cx, cy = px1((0.6, 0.6))
    ax = abs(px1((0.65, 0.6))[0] - cx)
    ay = abs(px1((0.6, 0.65))[1] - cy)
    expected_area = np.pi * ax * ay
    ratio = result.area_px / expected_area
    assert 0.75 < ratio < 1.25, f"面积换算偏差过大: {result.area_px:.0f} vs {expected_area:.0f}"
    print(f"[OK] 2 池内检出：({result.x:.3f},{result.y:.3f}) m  "
          f"期望({expected[0]:.3f},{expected[1]:.3f})  conf={result.confidence:.2f}  "
          f"area={result.area_px:.0f}px^2（椭圆理论 {expected_area:.0f}）")

    # 贴边目标也应能检出（不能因为 ROI 裁剪把池边目标吃掉）
    det2 = det_mod.Detector(yolo_enabled=False)
    frame_edge, expected_edge = frame_with((0.10, 0.10), seed=1)
    edge = det2.detect(frame_edge, H_MAT)
    assert edge is not None, "贴边目标被误拒"
    assert close_to(edge.x, expected_edge[0], 0.03) and close_to(edge.y, expected_edge[1], 0.03), edge
    print(f"[OK] 2b 贴边目标：({edge.x:.3f},{edge.y:.3f}) m  conf={edge.confidence:.2f}")


# ---------------------------------------------------------------------------
# 3. 池外目标被拒
# ---------------------------------------------------------------------------
def test_outside_pool_rejected() -> None:
    # (a) 池外只有橙色大块 -> None
    det = det_mod.Detector(yolo_enabled=False)
    frame = make_water(np.random.default_rng(2))
    draw_blob_px(frame, (200, 350), 60)            # 在 ROI 外接矩形内、但在水池梯形之外
    assert det.detect(frame, H_MAT) is None, "池外橙色被误检为落水目标"
    print("[OK] 3a 池外大块橙色（落在 ROI 外接矩形斜角）被拒")

    # (b) 池外大块 + 池内小目标：必须返回池内目标，而不是"面积最大的轮廓"
    det2 = det_mod.Detector(yolo_enabled=False)
    frame2, expected = frame_with((0.6, 0.55), seed=3)
    draw_blob_px(frame2, (200, 350), 60)           # 面积比池内浮球大 3~4 倍
    result = det2.detect(frame2, H_MAT)
    assert result is not None, "有池外干扰时池内目标反而丢了"
    assert close_to(result.x, expected[0], TOL_M) and close_to(result.y, expected[1], TOL_M), result
    print(f"[OK] 3b 池外大块橙色未抢走目标：仍返回 ({result.x:.3f},{result.y:.3f}) m")

    # (c) 画面角落（ROI 之外）的橙色
    det3 = det_mod.Detector(yolo_enabled=False)
    frame3 = make_water(np.random.default_rng(4))
    draw_blob_px(frame3, (40, 60), 35)
    assert det3.detect(frame3, H_MAT) is None
    print("[OK] 3c 画面角落（ROI 之外）的橙色被拒")


# ---------------------------------------------------------------------------
# 4. 无目标
# ---------------------------------------------------------------------------
def test_no_target() -> None:
    det = det_mod.Detector(yolo_enabled=False)
    frame = make_water(np.random.default_rng(5))
    for i in range(5):
        assert det.detect(frame, H_MAT) is None, f"第 {i} 帧无目标却返回了检测结果"
    print("[OK] 4 无目标：连续 5 帧返回 None")


# ---------------------------------------------------------------------------
# 5. 形状异常被拒
# ---------------------------------------------------------------------------
def test_bad_shapes_rejected() -> None:
    # (a) 细长反光条：面积很大，但填充率极低 + 长宽比极端
    det = det_mod.Detector(yolo_enabled=False)
    frame = make_water(np.random.default_rng(6))
    p1 = np.array(px1((0.25, 0.95)))
    p2 = np.array(px1((0.95, 0.25)))
    direction = p2 - p1
    direction /= np.linalg.norm(direction)
    normal = np.array([-direction[1], direction[0]]) * 4.0
    quad = np.array([p1 + normal, p2 + normal, p2 - normal, p1 - normal], dtype=np.int32)
    cv2.fillPoly(frame, [quad], ORANGE)
    assert det.detect(frame, H_MAT) is None, "细长反光条被当成目标"
    print("[OK] 5a 细长反光条（填充率≈0.01）被拒")

    # (b) 面积过小的橙色点
    det2 = det_mod.Detector(yolo_enabled=False)
    frame2 = make_water(np.random.default_rng(7))
    draw_blob_px(frame2, px1((0.6, 0.6)), 4)       # 面积 ~50 px^2 < MIN_TARGET_AREA_PX
    assert det2.detect(frame2, H_MAT) is None, "过小噪点被当成目标"
    print("[OK] 5b 面积极小的橙色点被拒")

    # (c) 看起来很"大"但只是细线框（空心方框，凸度低/填充率低）
    det3 = det_mod.Detector(yolo_enabled=False)
    frame3 = make_water(np.random.default_rng(8))
    a = np.array(px1((0.3, 0.3)), dtype=np.int32)
    b = np.array(px1((0.9, 0.75)), dtype=np.int32)
    cv2.rectangle(frame3, tuple(a), tuple(b), ORANGE, 3)
    assert det3.detect(frame3, H_MAT) is None, "空心细框被当成目标"
    print("[OK] 5c 空心细框（填充率低）被拒")


# ---------------------------------------------------------------------------
# 6. HSV 段：默认多段 vs 显式单段
# ---------------------------------------------------------------------------
def test_hsv_ranges() -> None:
    red = (20, 20, 220)            # BGR 正红：H≈0，会被内置"背光偏红橙"补段覆盖

    # (a) 显式只给橙色主段 -> 红色被拒
    d_single = det_mod.Detector(
        hsv_ranges=[((5, 120, 120), (22, 255, 255))], yolo_enabled=False
    )
    frame_r = make_water(np.random.default_rng(9))
    draw_buoy(frame_r, (0.6, 0.6), color=red)
    assert d_single.detect(frame_r, H_MAT) is None, "单段橙色阈值不应检出正红"

    # (b) 默认多段（config 主段 + 内置补段）-> 红色可检
    d_multi = det_mod.Detector(yolo_enabled=False)
    det_r = d_multi.detect(frame_r, H_MAT)
    assert det_r is not None, "默认多段 HSV 应覆盖偏红橙"

    # (c) 自定义只匹配红色 -> 红色可检、橙色反而被拒
    d_red = det_mod.Detector(
        hsv_ranges=[((0, 150, 150), (4, 255, 255))], yolo_enabled=False
    )
    assert d_red.detect(frame_r, H_MAT) is not None
    frame_o = make_water(np.random.default_rng(10))
    draw_buoy(frame_o, (0.6, 0.6), color=ORANGE)
    # 注意：必须换一个新实例。同一个 detector 上一帧检到了红球，本帧检不到时
    # 跟踪器会"保持"上一帧轨迹最多 lost_frames 帧（这是设计行为，不是误检）。
    d_red_o = det_mod.Detector(
        hsv_ranges=[((0, 150, 150), (4, 255, 255))], yolo_enabled=False
    )
    assert d_red_o.detect(frame_o, H_MAT) is None, "自定义红色段不应检出橙色"

    # (d) 面积阈值可覆盖
    d_big = det_mod.Detector(min_area_px=20000, yolo_enabled=False)
    frame_o2 = make_water(np.random.default_rng(11))
    draw_buoy(frame_o2, (0.6, 0.6), radius_m=0.03)
    assert d_big.detect(frame_o2, H_MAT) is None, "min_area_px 覆盖没生效"
    print("[OK] 6 HSV：多段/单段/自定义段/min_area_px 覆盖均符合预期")


# ---------------------------------------------------------------------------
# 7. 连续跟踪 + 速度估计
# ---------------------------------------------------------------------------
def test_tracking() -> None:
    fps = 30.0
    det = det_mod.Detector(yolo_enabled=False, fps=fps)
    x0, step, y = 0.25, 0.024, 0.40
    track_ids = set()
    last = None
    max_jump = 0.0
    for i in range(26):
        frame = make_water(np.random.default_rng(100 + i))
        draw_buoy(frame, (x0 + i * step, y))
        result = det.detect(frame, H_MAT)
        assert result is not None, f"第 {i} 帧跟丢"
        track_ids.add(result.track_id)
        if last is not None:
            max_jump = max(max_jump, abs(result.x - last.x))
        last = result

    assert len(track_ids) == 1, f"track_id 发生跳变: {track_ids}"
    assert max_jump < 0.06, f"位置抖动过大: {max_jump:.3f} m/帧"
    true_last = x0 + 25 * step
    assert abs(last.x - true_last) < 0.05, (last.x, true_last)

    state = det.track_state()
    assert len(state) == 1, state
    vx = state[0]["vx"]
    assert 0.4 < vx < 1.2, f"速度估计不合理: vx={vx:.2f}（真值 {step * fps:.2f} m/s）"
    assert abs(state[0]["vy"]) < 0.25, f"y 方向速度应接近 0: vy={state[0]['vy']:.2f}"
    print(f"[OK] 7 跟踪：26 帧 track_id={track_ids.pop()} 稳定，最大帧间跳变 {max_jump:.4f} m，"
          f"速度估计 vx={vx:.2f} m/s（真值 {step * fps:.2f}）")


# ---------------------------------------------------------------------------
# 8. 短暂遮挡后重新捕获：track_id 不变
# ---------------------------------------------------------------------------
def test_reacquire() -> None:
    det = det_mod.Detector(yolo_enabled=False, fps=30.0, lost_frames=6)
    pos = (0.45, 0.55)
    frame = make_water(np.random.default_rng(20))
    draw_buoy(frame, pos)
    first = det.detect(frame, H_MAT)
    assert first is not None
    for _ in range(3):                                  # 遮挡 3 帧（未超过 lost_frames）
        assert det.detect(make_water(np.random.default_rng(21)), H_MAT) is not None
    frame2 = make_water(np.random.default_rng(22))
    draw_buoy(frame2, pos)
    again = det.detect(frame2, H_MAT)
    assert again is not None
    assert again.track_id == first.track_id, (first.track_id, again.track_id)
    assert again.confidence > 0.5, "重新捕获后置信度应恢复到接近观测值"
    print(f"[OK] 8 遮挡 3 帧后重捕：track_id 保持 {again.track_id}，conf 回升到 {again.confidence:.2f}")


# ---------------------------------------------------------------------------
# 9. 丢失：置信度衰减 + 最终 None（不长期沿用陈旧坐标）
# ---------------------------------------------------------------------------
def test_lost() -> None:
    lost_frames = 6
    det = det_mod.Detector(yolo_enabled=False, fps=30.0, lost_frames=lost_frames)
    frame = make_water(np.random.default_rng(30))
    draw_buoy(frame, (0.5, 0.5))
    first = det.detect(frame, H_MAT)
    assert first is not None
    conf0 = first.confidence

    confs = []
    for i in range(lost_frames):
        result = det.detect(make_water(np.random.default_rng(31 + i)), H_MAT)
        assert result is not None, f"丢失第 {i + 1} 帧就判丢了（应保留 {lost_frames} 帧）"
        # 位置冻结：不沿用速度外推，也不乱跳
        assert close_to(result.x, first.x, 1e-9) and close_to(result.y, first.y, 1e-9), \
            f"丢失期间坐标漂移: ({result.x},{result.y}) vs ({first.x},{first.y})"
        confs.append(result.confidence)

    assert all(b < a for a, b in zip(confs, confs[1:])), f"置信度未单调衰减: {confs}"
    assert confs[-1] < 0.5 * conf0, f"衰减太慢: {confs[-1]:.3f} vs {conf0:.3f}"

    # 超过 lost_frames 必须返回 None
    final = det.detect(make_water(np.random.default_rng(40)), H_MAT)
    assert final is None, "超过 lost_frames 仍在返回陈旧坐标"
    assert det.track_state() == [], det.track_state()
    print(f"[OK] 9 丢失：conf {conf0:.2f} -> {confs[-1]:.2f}"
          f"（{lost_frames} 帧衰减，逐帧 {conf0 / max(confs[0], 1e-9):.2f}x），"
          f"第 {lost_frames + 1} 帧返回 None")

    # reset() 也要清干净
    det.reset()
    assert det.track_state() == []
    print("[OK] 9b reset() 清空轨迹")


# ---------------------------------------------------------------------------
# 10. YOLOv8 输出解码
# ---------------------------------------------------------------------------
def _yolo_output(n_anchors: int = 100, cls0_conf: float = 0.9,
                 cls2_conf: float = 0.95) -> np.ndarray:
    """构造 (1,84,N)：anchor0 = person 0.9，anchor1 = car(class 2) 0.95。"""
    out = np.zeros((1, 84, n_anchors), dtype=np.float32)
    out[0, 0, 0], out[0, 1, 0], out[0, 2, 0], out[0, 3, 0] = 320.0, 300.0, 40.0, 80.0
    out[0, 4 + 0, 0] = cls0_conf
    out[0, 0, 1], out[0, 1, 1], out[0, 2, 1], out[0, 3, 1] = 500.0, 200.0, 100.0, 60.0
    out[0, 4 + 2, 1] = cls2_conf
    return out


def test_yolo_decode() -> None:
    out = _yolo_output()
    boxes = det_mod.Detector.decode_yolo_output(out, 0.35, (0,))
    assert len(boxes) == 1, boxes
    x1, y1, x2, y2, conf, cls = boxes[0]
    assert cls == 0 and abs(conf - 0.9) < 1e-6
    assert (x1, y1, x2, y2) == (300.0, 260.0, 340.0, 340.0), boxes[0]

    # 不过滤类别 -> 两个框，按置信度降序
    boxes_all = det_mod.Detector.decode_yolo_output(out, 0.35, None)
    assert len(boxes_all) == 2, boxes_all
    assert boxes_all[0][5] == 2 and boxes_all[1][5] == 0

    # 置信度阈值
    assert det_mod.Detector.decode_yolo_output(out, 0.96, None) == []

    # 1x5xN（单类别导出）
    single = np.zeros((1, 5, 50), dtype=np.float32)
    single[0, :4, 3] = [320.0, 300.0, 40.0, 80.0]
    single[0, 4, 3] = 0.8
    dec = det_mod.Detector.decode_yolo_output(single, 0.35, (0,))
    assert len(dec) == 1 and dec[0][5] == 0 and abs(dec[0][4] - 0.8) < 1e-6, dec

    # 退化输入不应崩
    assert det_mod.Detector.decode_yolo_output(np.zeros((1, 3, 5), np.float32), 0.3, (0,)) == []
    assert det_mod.Detector.decode_yolo_output(np.zeros((0,), np.float32), 0.3, (0,)) == []
    print("[OK] 10 YOLOv8 解码：1x84xN / 1x5xN / 类别过滤 / 阈值 / 退化输入")


def test_letterbox() -> None:
    img = np.zeros((960, 1280, 3), dtype=np.uint8)
    padded, ratio, pad_x, pad_y = det_mod.Detector._letterbox(img, 640)
    assert padded.shape == (640, 640, 3), padded.shape
    assert abs(ratio - 0.5) < 1e-6, ratio
    assert pad_x == 0 and pad_y == 80, (pad_x, pad_y)

    img2 = np.zeros((1080, 1920, 3), dtype=np.uint8)
    padded2, ratio2, _, pad_y2 = det_mod.Detector._letterbox(img2, 640)
    assert padded2.shape == (640, 640, 3)
    assert abs(ratio2 - 640.0 / 1920.0) < 1e-6
    assert pad_y2 == round((640 - 1080 * 640.0 / 1920.0) / 2.0), pad_y2
    print(f"[OK] 11 letterbox：1280x960 -> 640x640 ratio={ratio:.3f} pad_y={pad_y}；"
          f"1920x1080 -> ratio={ratio2:.4f} pad_y={pad_y2}")


# ---------------------------------------------------------------------------
# 12. 融合策略（FakeNet 注入，不依赖真模型）
# ---------------------------------------------------------------------------
class FakeNet:
    """最小可用的 cv2.dnn.Net 替身：固定输出一份 1x84x8400 的 YOLOv8 结果。"""

    def __init__(self, output: np.ndarray):
        self.output = output
        self.calls = 0
        self.last_blob = None

    def setInput(self, blob):
        self.last_blob = blob

    def getUnconnectedOutLayersNames(self):
        return ["output0"]

    def forward(self, names=None):
        self.calls += 1
        return [self.output]


def _person_output_at_px(bottom_px, conf: float = 0.9, w: float = 50.0, h: float = 120.0) -> np.ndarray:
    """按 letterbox 逆变换反推：让框底边中点恰好落在指定的**原图**像素上。"""
    out = np.zeros((1, 84, 8400), dtype=np.float32)
    ratio = 0.5
    pad_x, pad_y = 0.0, 80.0
    x_lb = bottom_px[0] * ratio + pad_x
    y_lb = bottom_px[1] * ratio + pad_y
    out[0, 0, 0] = x_lb
    out[0, 1, 0] = y_lb - h / 2.0
    out[0, 2, 0] = w
    out[0, 3, 0] = h
    out[0, 4, 0] = conf
    return out


def _attach_fake_net(det: det_mod.Detector, output: np.ndarray) -> FakeNet:
    net = FakeNet(output)
    det._net = net                        # 测试内部注入，等价于"模型加载成功"
    det.yolo_enabled = True
    det._yolo_cache = None
    det._yolo_cache_ready = False
    det._yolo_cache_shape = None
    det._yolo_tick = 0
    return net


def test_fusion() -> None:
    pool_center_px = px1((0.6, 0.6))

    # (a) 人形高置信 -> source == "yolo"，坐标落在池心
    d = det_mod.Detector(yolo_enabled=False, yolo_every=1)
    frame = make_water(np.random.default_rng(50))
    _attach_fake_net(d, _person_output_at_px(pool_center_px, conf=0.9))
    det = d.detect(frame, H_MAT)
    assert det is not None and det.source == "yolo", det
    assert close_to(det.x, 0.6, 0.01) and close_to(det.y, 0.6, 0.01), det
    print(f"[OK] 12a 高置信人形优先：source=yolo ({det.x:.3f},{det.y:.3f}) conf={det.confidence:.2f}")

    # (b) 人形低置信（>= 检出底噪 yolo_conf=0.35、但 < 优先阈值 0.45）+ 有颜色目标
    #     -> 让位给传统检测
    d2 = det_mod.Detector(yolo_enabled=False, yolo_every=1)
    frame2, _ = frame_with((0.45, 0.65), seed=51)
    _attach_fake_net(d2, _person_output_at_px(pool_center_px, conf=0.40))
    det2 = d2.detect(frame2, H_MAT)
    assert det2 is not None and det2.source == "classical", det2
    print(f"[OK] 12b 低置信人形让位：source=classical ({det2.x:.3f},{det2.y:.3f})")

    # (c) 人形低置信 + 无颜色目标 -> 仍然接受（比 None 有用）
    d3 = det_mod.Detector(yolo_enabled=False, yolo_every=1)
    frame3 = make_water(np.random.default_rng(52))
    _attach_fake_net(d3, _person_output_at_px(pool_center_px, conf=0.40))
    det3 = d3.detect(frame3, H_MAT)
    assert det3 is not None and det3.source == "yolo", det3
    print("[OK] 12c 低置信人形在无颜色目标时兜底采用")

    # (d) 池外人形（底边落在池下方）-> 被拒
    d4 = det_mod.Detector(yolo_enabled=False, yolo_every=1)
    frame4 = make_water(np.random.default_rng(53))
    _attach_fake_net(d4, _person_output_at_px((650, 1000), conf=0.95))
    assert d4.detect(frame4, H_MAT) is None, "池外人形未被拒绝"
    print("[OK] 12d 池外人形（底边在水池外）被拒")

    # (e) 抽帧推理：yolo_every=3 时前向次数应约为帧数/3
    d5 = det_mod.Detector(yolo_enabled=False, yolo_every=3)
    net = _attach_fake_net(d5, _person_output_at_px(pool_center_px, conf=0.9))
    for _ in range(9):
        d5.detect(frame, H_MAT)
    # 首帧必跑（缓存为空），之后每 3 帧一次：第 1,3,6,9 帧 -> 4 次
    assert net.calls == 4, f"yolo_every=3 时 9 帧应推理 4 次，实际 {net.calls}"
    print(f"[OK] 12e 抽帧推理：9 帧 / yolo_every=3 -> 前向 {net.calls} 次")


# ---------------------------------------------------------------------------
# 13. 真实 ONNX 模型（存在则加载并推理）
# ---------------------------------------------------------------------------
def test_real_onnx_if_present() -> None:
    d = det_mod.Detector(yolo_enabled=True)
    info = d.info()
    if not info["yolo_enabled"]:
        print("[SKIP] 13 未找到 ONNX 模型（vision/models/），YOLO 后端按设计静默禁用")
        assert d.info()["notes"], "禁用时应留下提示信息"
        print(f"       提示: {d.notes[-1]}")
        return

    frame, _ = frame_with((0.6, 0.6), seed=60)
    det = d.detect(frame, H_MAT)
    assert det is not None, "启用 ONNX 后传统路径也不该失效"
    t0 = time.perf_counter()
    for _ in range(3):
        d._yolo_infer(frame, H_MAT)
    ms = (time.perf_counter() - t0) / 3.0 * 1000.0
    print(f"[OK] 13 真实 ONNX：{Path(info['yolo_model']).name} 已加载，"
          f"640x640 单次前向 {ms:.1f} ms（每 {d.yolo_every} 帧一次）"
          f"；本帧 source={det.source}")

    # 显式给一个不存在的模型路径 -> 禁用而不是抛异常
    d_bad = det_mod.Detector(model_path="no_such_model.onnx")
    assert d_bad.yolo_enabled is False
    print("[OK] 13b 指定不存在的模型路径 -> 静默禁用，不抛异常")


def test_yolo_disabled() -> None:
    d = det_mod.Detector(yolo_enabled=False)
    assert d.yolo_enabled is False
    assert d.info()["yolo_model"] is None
    frame, expected = frame_with((0.6, 0.6), seed=61)
    det = d.detect(frame, H_MAT)
    assert det is not None and det.source == "classical"
    print("[OK] 13c yolo_enabled=False：不加载模型，传统路径正常")


# ---------------------------------------------------------------------------
# 14. 1080P 单帧耗时
# ---------------------------------------------------------------------------
def test_performance() -> None:
    w, h = 1920, 1080
    quad_1080 = POOL_QUAD * 1.5                       # 1500x900 的水池，贴近真实占屏
    H1080 = pool.compute_homography(quad_1080)

    def make_1080p(offset_m: float) -> np.ndarray:
        img = make_water(np.random.default_rng(70), w, h)
        cx, cy = px([(0.6 + offset_m, 0.6)])[0]        # 用 1280 的 H 画完再缩放到 1080P
        cx, cy = cx * 1.5, cy * 1.5
        cv2.ellipse(img, (int(cx), int(cy)), (60, 48), 0, 0, 360, ORANGE, -1)
        return img

    det = det_mod.Detector(yolo_enabled=False)
    frames = [make_1080p(i * 0.01) for i in range(25)]
    for f in frames[:5]:                               # 预热（ROI 缓存/内存分配）
        det.detect(f, H1080)
    t0 = time.perf_counter()
    n = 20
    hits = 0
    for i in range(n):
        if det.detect(frames[5 + i], H1080) is not None:
            hits += 1
    mean_ms = (time.perf_counter() - t0) / n * 1000.0
    assert hits == n, f"1080P 下 {n - hits} 帧跟丢"
    print(f"[OK] 14 传统路径 1080P：{mean_ms:.2f} ms/帧（{hits}/{n} 帧检出，"
          f"ROI 长边 <= {det.roi_max_side}px）")
    assert mean_ms < 40.0, f"1080P 传统路径单帧 {mean_ms:.1f} ms，超出预算"

    if det_mod.MODELS_DIR.is_dir() and any(det_mod.MODELS_DIR.glob("*.onnx")):
        d_yolo = det_mod.Detector(yolo_enabled=True, yolo_every=3)
        if d_yolo.yolo_enabled:
            for f in frames[:3]:
                d_yolo.detect(f, H1080)
            t0 = time.perf_counter()
            for i in range(9):
                d_yolo.detect(frames[i], H1080)
            yolo_ms = (time.perf_counter() - t0) / 9.0 * 1000.0
            print(f"[OK] 14b 开启 ONNX（每 3 帧一次）1080P：{yolo_ms:.2f} ms/帧均值")
            assert yolo_ms < 90.0, f"ONNX 路径单帧 {yolo_ms:.1f} ms，超出预算"


# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 78)
    print("detector.py 合成帧回归测试（无需相机 / 无需真实模型）")
    print(f"OpenCV {cv2.__version__} / numpy {np.__version__} / "
          f"config 分辨率 {W}x{H} / 水池 {POOL_M} m")
    print("=" * 78)
    t0 = time.perf_counter()
    test_geometry()
    test_detect_in_pool()
    test_outside_pool_rejected()
    test_no_target()
    test_bad_shapes_rejected()
    test_hsv_ranges()
    test_tracking()
    test_reacquire()
    test_lost()
    test_yolo_decode()
    test_letterbox()
    test_fusion()
    test_real_onnx_if_present()
    test_yolo_disabled()
    test_performance()
    print("=" * 78)
    print(f"全部断言通过（{time.perf_counter() - t0:.2f} s）")
    print("=" * 78)


if __name__ == "__main__":
    main()
