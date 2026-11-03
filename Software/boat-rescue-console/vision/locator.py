"""
智护库安 —— 全局视觉定位（上位机）

职责：用顶端 UVC 相机俯拍水池，识别
  1) 船顶 ArUco 码（ID 0）-> 船的全局坐标 (boat_x, boat_y) + 航向 boat_heading
  2) 落水目标（颜色/轮廓）-> 目标全局坐标 (target_x, target_y)
然后把坐标 POST 给本地 Node 服务（serial-service/index.js），由它统一管串口下发。

为什么坐标不直接发串口：
  串口同一时刻只能被一个进程占用。若本程序直接持有串口，网页就无法连接、
  也看不到遥测。改成喂给 Node 服务后，网页与视觉程序可以同时运行，
  且视觉停推后 400 ms 内自动把控制权交还网页。

水池坐标系：标定时鼠标点的四点决定，左下为原点，X 向右、Y 向上，量程 1.2 m。
航向定义：0° 指向 +Y，顺时针增大（与船端 PID 的 atan2(dx, dy) 一致）。

用法：
  python locator.py --calibrate    # 标定（鼠标点水池四角）
  python locator.py                # 正常定位（需相机）
  python locator.py --simulate     # 无相机模拟，验证整条链路
  python locator.py --show         # 显示识别画面
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import threading
import time
import urllib.error
import urllib.request

import config
import pool as pool_mod

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    cv2 = None
    HAS_CV2 = False

# 注意：boat / target 模块依赖 OpenCV，这里**延迟导入**，
# 这样没装 OpenCV 也能用 --simulate / --calibrate 之前的部分。
# （--calibrate 本身需要 OpenCV，会在调用处给出提示。）


# --------------------------------------------------------------------------
# 上报客户端
# --------------------------------------------------------------------------
class Reporter:
    """把船/目标坐标推给 Node 服务。

    **为什么要异步**：原来是同步 HTTP，超时 0.5 s。一旦服务端稍慢，主循环
    就被阻塞半秒 —— 实测 ageMs 因此跳到 689 ms，超过服务端 400 ms 的视觉
    超时，mission_state 在 1(自主) 和 0(待命) 之间反复跳，船"刚启动就停"。
    现在改成后台线程发最新一帧（覆盖旧值，不做队列堆积），主循环永不阻塞。
    """

    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/api/navigation"
        self.fail_count = 0
        self.ok_count = 0
        self._last_warn = 0.0
        self._lock = threading.Lock()
        self._pending: dict | None = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def _worker(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                payload = self._pending
                self._pending = None
            if payload is None:
                time.sleep(0.005)
                continue
            self._post(payload)

    def _post(self, payload: bytes) -> None:
        req = urllib.request.Request(
            self.url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                resp.read()
            self.ok_count += 1
            self.fail_count = 0
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            self.fail_count += 1
            now = time.time()
            if now - self._last_warn >= 5.0:
                self._last_warn = now
                print(f"[警告] 上报失败({self.fail_count}): {exc} —— 请确认已运行 npm run dev",
                      file=sys.stderr)

    def send(self, boat_x, boat_y, heading, target_x, target_y) -> None:
        payload = json.dumps(
            {
                "boatX": round(boat_x, 4),
                "boatY": round(boat_y, 4),
                # 先取模再取整：否则 359.996° 会被 round 成 360.0，
                # 而服务端要求 heading < 360，整帧会被 400 丢掉。
                "heading": round(heading, 2) % 360.0,
                "targetX": round(target_x, 4),
                "targetY": round(target_y, 4),
            }
        ).encode("utf-8")
        with self._lock:
            self._pending = payload      # 只保留最新一帧，不排队

    def release(self) -> None:
        """停止推送，交还控制权给网页。"""
        self._stop.set()
        try:
            req = urllib.request.Request(self.url, method="DELETE")
            urllib.request.urlopen(req, timeout=0.5).read()
            print("已停止推送坐标，控制权交还网页")
        except Exception:
            pass


# --------------------------------------------------------------------------
# 模拟模式：不需要相机，用运动学模型生成坐标，验证整条链路
# --------------------------------------------------------------------------
class SimulatedBoat:
    """
    模拟一条船从起点驶向目标：先原地转向对准，再直行接近。

    用途：相机还没到位时，验证"Python 上报 -> Node 编码 -> 串口 -> 船端">
    这条链路是否通畅，以及网页/桥接板屏幕能否显示坐标。
    """

    def __init__(self, target=(0.9, 0.9), start=(0.2, 0.2), speed=0.25, turn_rate=90.0):
        self.x, self.y = start
        self.tx, self.ty = target
        self.speed = speed            # m/s
        self.turn_rate = turn_rate    # deg/s
        self.heading = 0.0
        self._last_t = time.time()

    def step(self) -> tuple[float, float, float, float, float]:
        now = time.time()
        dt = min(max(now - self._last_t, 0.0), 0.2)
        self._last_t = now

        dx, dy = self.tx - self.x, self.ty - self.y
        dist = math.hypot(dx, dy)

        if dist > 1e-4:
            desired = math.degrees(math.atan2(dx, dy)) % 360.0
            err = (desired - self.heading + 180.0) % 360.0 - 180.0

            # 先转向：误差大就只转不走
            max_turn = self.turn_rate * dt
            turn = max(-max_turn, min(max_turn, err))
            self.heading = (self.heading + turn) % 360.0

            if abs(err) < 25.0:       # 对准后才前进
                move = min(self.speed * dt, dist)
                rad = math.radians(self.heading)
                self.x += move * math.sin(rad)
                self.y += move * math.cos(rad)

            # 到了就换一个新目标，持续演示
            if dist < 0.05:
                self.tx, self.ty = (0.2, 0.9) if self.tx > 0.5 else (0.9, 0.2)
                print(f"[模拟] 到达目标，切换新目标 ({self.tx}, {self.ty})")

        return self.x, self.y, self.heading, self.tx, self.ty


# --------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------
def open_camera() -> tuple[cv2.VideoCapture, int, int]:
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    if not cap.isOpened():
        raise RuntimeError(
            f"无法打开相机 index={config.CAMERA_INDEX}。"
            "请确认相机已连接；若只想验证链路，可用 --simulate"
        )
    # MJPG 才能在高分辨率下拿到流畅帧率
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*config.CAMERA_FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.FRAME_HEIGHT)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"相机已打开: {w}x{h} @ {config.CAMERA_FOURCC}")
    return cap, w, h


def _in_pool(value: float) -> bool:
    """坐标是否落在水池内（留一点余量，容忍贴边）。"""
    return -config.POOL_REPORT_MARGIN_M <= value <= pool_mod.POOL_SIZE_M + config.POOL_REPORT_MARGIN_M


def reportable(pose, tgt) -> bool:
    """
    只在"船和目标都在水池范围内"时上报。

    这是最后一道地理围栏：颜色误检/ArUco 误识别给出的离谱坐标如果照发，
    船会照着跑出池子；跳过上报后，服务端 400 ms 视觉超时会自动把船停下来。
    """
    return all(_in_pool(v) for v in (pose.x, pose.y, tgt.x, tgt.y))


def build_detector():
    """
    构造目标检测器：优先 detector.py 的融合检测（HSV+形状+跟踪，可选 ONNX 人形），
    不可用时回退 target.py 的旧 HSV 实现（保证任何环境都能跑）。
    """
    from target import TargetDetector

    if not config.USE_FUSED_DETECTOR:
        return TargetDetector(), "旧版 HSV（target.py）"

    try:
        from detector import Detector

        det = Detector(
            yolo_enabled=config.YOLO_ENABLED,
            yolo_every=config.YOLO_EVERY_N,
            yolo_conf=config.YOLO_CONF,
            model_path=getattr(config, "YOLO_MODEL", "") or None,
            yolo_input_size=getattr(config, "YOLO_INPUT_SIZE", 640),
        )
        info = det.info()
        label = "融合检测 + ONNX 人形" if info.get("yolo_enabled") else "融合检测（传统）"
        return det, label
    except Exception as exc:                      # noqa: BLE001 - 任何异常都退回旧实现
        print(f"[警告] 融合检测器不可用（{exc}），回退到 target.py", file=sys.stderr)
        return TargetDetector(), "旧版 HSV（回退）"


def build_planner():
    """
    构造 A* + 覆盖搜索 + 纯追踪规划器。

    规划器只决定"下发的 target 写哪个点"：真实目标可见时输出沿 A* 路径前方的
    虚拟目标（保证 >0.4 m，避免船端提前切二哈末端）；没有目标且开启了覆盖搜索时
    输出弓字形航线上的虚拟目标。协议完全不变（仍是 26 字节里的 target_x/target_y）。
    """
    if not config.USE_PLANNER:
        return None
    try:
        from planner import Planner, PoolPlanner

        pool_planner = PoolPlanner(
            size_m=pool_mod.POOL_SIZE_M,
            resolution_m=config.PLANNER_RESOLUTION_M,
            boat_radius_m=config.PLANNER_BOAT_RADIUS_M,
            clearance_m=config.PLANNER_CLEARANCE_M,
        )
        return Planner(pool_planner=pool_planner, lookahead_m=config.PLANNER_LOOKAHEAD_M)
    except Exception as exc:                      # noqa: BLE001
        print(f"[警告] 规划器不可用（{exc}），退回直接下发目标坐标", file=sys.stderr)
        return None


def run_real(show: bool) -> None:
    if not HAS_CV2:
        raise RuntimeError("实时定位需要 OpenCV，请先安装: pip install opencv-python")

    from boat import BoatDetector

    info = pool_mod.load_calibration_info()
    H = info["homography"]
    boat = BoatDetector(config.ARUCO_ID)
    target, detector_label = build_detector()

    # 非矩形水池：把标定里存的多边形注入检测器，否则池壁附近的有效目标会被判成池外
    polygon_m = info.get("pool_polygon_m")
    if polygon_m and hasattr(target, "set_pool_polygon"):
        target.set_pool_polygon(polygon_m)
        print(f"水池轮廓：多边形 {len(polygon_m)} 点（来自标定文件）")
    elif hasattr(target, "set_pool_polygon"):
        print("水池轮廓：矩形（无 pool_polygon_m，按 0~POOL_SIZE_M 范围判定）")

    planner = build_planner()
    reporter = Reporter(config.SERVER_URL)

    cap, frame_w, frame_h = open_camera()

    # 单应矩阵和分辨率强绑定：不一致时必须拒绝启动，否则坐标会静默缩放错。
    resolution_problem = pool_mod.check_resolution(info, frame_w, frame_h)
    if resolution_problem:
        cap.release()
        raise RuntimeError(resolution_problem)

    period = 1.0 / config.REPORT_HZ
    last_report = 0.0
    last_print = 0.0
    last_out_of_pool_warn = 0.0

    print(f"目标检测：{detector_label}")
    print(f"路径规划：{'A* + 覆盖搜索 + 纯追踪' if planner else '关闭（直接下发目标坐标）'}"
          f"    覆盖搜索：{'开' if config.SEARCH_WHEN_NO_TARGET else '关'}")
    print("开始定位（Ctrl+C 退出）")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[警告] 读取相机帧失败", file=sys.stderr)
                time.sleep(0.05)
                continue

            pose = boat.detect(frame, H)
            tgt = target.detect(frame, H)
            plan = None

            if pose is None:
                # 丢码时重置航向滤波，避免下次出现时残留旧航向
                boat.reset_filter()
                # 船位姿丢了就作废旧路径：恢复后从当前位置重新规划，避免沿旧路径冲
                if planner is not None and planner.mode is not None:
                    planner.reset()
            elif planner is not None:
                plan = planner.update(pose, tgt)

            now = time.time()
            if pose is not None and (now - last_report) >= period:
                if tgt is not None:
                    if reportable(pose, tgt):
                        # 有真实目标：下发规划后的虚拟目标（无规划器时就是目标本身）
                        tx, ty = (plan.target_x, plan.target_y) if plan is not None else (tgt.x, tgt.y)
                        if _in_pool(tx) and _in_pool(ty):
                            last_report = now
                            reporter.send(pose.x, pose.y, pose.heading, tx, ty)
                    elif now - last_out_of_pool_warn >= 2.0:
                        # 误检/丢码产生的离谱坐标不上报：服务端 400 ms 超时会自动停车
                        last_out_of_pool_warn = now
                        print(f"[警告] 定位超出水池范围，已跳过上报：船({pose.x:.2f},{pose.y:.2f}) "
                              f"目标({tgt.x:.2f},{tgt.y:.2f})", file=sys.stderr)
                elif config.SEARCH_WHEN_NO_TARGET and plan is not None:
                    # 没有真实目标：按覆盖航线巡航（虚拟目标恒在 0.5 m 外，不会提前切末端）
                    tx, ty = plan.target_x, plan.target_y
                    if _in_pool(tx) and _in_pool(ty):
                        last_report = now
                        reporter.send(pose.x, pose.y, pose.heading, tx, ty)

            if now - last_print >= 1.0:
                last_print = now
                b = f"({pose.x:.3f},{pose.y:.3f}) hdg={pose.heading:.1f}°" if pose else "未检测到船"
                t = f"({tgt.x:.3f},{tgt.y:.3f})" if tgt else "未检测到目标"
                extra = ""
                if plan is not None:
                    extra = f"   规划={plan.mode} 余{plan.remaining_m:.2f}m"
                    if tgt is None and config.SEARCH_WHEN_NO_TARGET:
                        extra += "（覆盖搜索）"
                    if pose is not None and tgt is not None:
                        # 三个距离本来就不相等，打出来避免误判：
                        #   真实 = 船到落水者；下发 = 船到虚拟前视点；余 = 沿路径剩余
                        d_true = math.hypot(tgt.x - pose.x, tgt.y - pose.y)
                        d_out = math.hypot(plan.target_x - pose.x, plan.target_y - pose.y)
                        tag = "直冲" if abs(plan.target_x - tgt.x) < 1e-6 and abs(plan.target_y - tgt.y) < 1e-6 else "追踪"
                        extra += f" 距真实{d_true:.2f} 距下发{d_out:.2f}({tag})"
                print(f"船 {b}   目标 {t}{extra}   上报 {reporter.ok_count} ok / {reporter.fail_count} fail")

            if show:
                # 叠加：池壁/网格/坐标轴 + 目标框与米坐标 + 船位与航向
                try:
                    import overlay as ov
                    status = [
                        (f"BOAT  {'({:.2f}, {:.2f}) hdg={:.0f}'.format(pose.x, pose.y, pose.heading) if pose else 'not found'}",
                         (80, 200, 80) if pose else (60, 60, 220)),
                        (f"TARGET {'({:.2f}, {:.2f})'.format(tgt.x, tgt.y) if tgt else 'not found'}"
                         + (f"  conf {tgt.confidence:.2f} {tgt.source}" if tgt else ""),
                         (80, 200, 80) if tgt else (60, 60, 220)),
                        (f"report ok={reporter.ok_count} fail={reporter.fail_count}",
                         (200, 200, 200)),
                    ]
                    if plan is not None:
                        detail = f"plan={plan.mode} remain={plan.remaining_m:.2f}m"
                        if pose is not None and tgt is not None:
                            d_true = math.hypot(tgt.x - pose.x, tgt.y - pose.y)
                            d_out = math.hypot(plan.target_x - pose.x, plan.target_y - pose.y)
                            direct = (abs(plan.target_x - tgt.x) < 1e-6
                                      and abs(plan.target_y - tgt.y) < 1e-6)
                            detail += f"  true={d_true:.2f} out={d_out:.2f} {'DIRECT' if direct else 'pursuit'}"
                        status.append((detail, (200, 200, 200)))
                    ov.render(
                        frame, H,
                        width_m=info.get("pool_width_m", pool_mod.POOL_SIZE_M),
                        height_m=info.get("pool_height_m", pool_mod.POOL_SIZE_M),
                        polygon_m=info.get("pool_polygon_m"),
                        target_box_px=getattr(tgt, "box_px", None) if tgt else None,
                        target_m=(tgt.x, tgt.y) if tgt else None,
                        target_conf=getattr(tgt, "confidence", None) if tgt else None,
                        target_source=getattr(tgt, "source", None) if tgt else None,
                        boat=(pose.x, pose.y, pose.heading) if pose else None,
                        status_lines=status,
                    )
                except Exception as exc:      # 可视化失败不能影响主流程
                    if not getattr(run_real, "_overlay_warned", False):
                        run_real._overlay_warned = True
                        print(f"[警告] 叠加显示失败（{exc}），退回原始画面", file=sys.stderr)
                cv2.imshow("locator", frame)
                if (cv2.waitKey(1) & 0xFF) == ord("q"):
                    break
    except KeyboardInterrupt:
        print("\n已中断")
    finally:
        cap.release()
        if show:
            cv2.destroyAllWindows()
        reporter.release()


def run_simulate() -> None:
    boat = SimulatedBoat()
    reporter = Reporter(config.SERVER_URL)
    period = 1.0 / config.REPORT_HZ
    last = 0.0
    print("模拟模式：不打开相机，直接按运动学模型生成坐标")
    print("  验证项目：Python 上报 -> Node 编码 -> 串口 -> 船端/桥接板屏幕")
    print("  Ctrl+C 退出")
    try:
        while True:
            x, y, hdg, tx, ty = boat.step()
            now = time.time()
            if now - last >= period:
                last = now
                reporter.send(x, y, hdg, tx, ty)
                print(f"\r模拟: 船=({x:.3f},{y:.3f}) 航向={hdg:5.1f}° 目标=({tx:.2f},{ty:.2f})"
                      f"  上报 {reporter.ok_count} ok / {reporter.fail_count} fail",
                      end="", flush=True)
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n已中断")
    finally:
        reporter.release()


def main() -> None:
    ap = argparse.ArgumentParser(description="智护库安 全局视觉定位")
    ap.add_argument("--calibrate", action="store_true", help="交互式标定水池四角")
    ap.add_argument("--simulate", action="store_true", help="无相机模拟模式（验证链路）")
    ap.add_argument("--show", action="store_true", help="显示识别画面")
    ap.add_argument("--camera", type=int, default=None, help="覆盖相机 index")
    ap.add_argument("--search", action="store_true",
                    help="无目标时按弓字形覆盖搜索（开启后一启动船就会自己动，台架调试慎用）")
    ap.add_argument("--no-planner", action="store_true",
                    help="关闭 A*/覆盖/纯追踪，直接把目标坐标发下去")
    ap.add_argument("--no-yolo", action="store_true", help="关闭 ONNX 人形模型，只用传统检测")
    ap.add_argument("--legacy-detector", action="store_true",
                    help="使用 target.py 的旧 HSV 检测（回滚用）")
    args = ap.parse_args()

    if args.camera is not None:
        config.CAMERA_INDEX = args.camera
    if args.search:
        config.SEARCH_WHEN_NO_TARGET = True
    if args.no_planner:
        config.USE_PLANNER = False
    if args.no_yolo:
        config.YOLO_ENABLED = False
    if args.legacy_detector:
        config.USE_FUSED_DETECTOR = False

    if args.calibrate:
        if not HAS_CV2:
            print("[错误] 标定需要 OpenCV，请先安装: pip install opencv-python", file=sys.stderr)
            sys.exit(1)
        pool_mod.calibrate_interactively(
            config.CAMERA_INDEX, config.FRAME_WIDTH, config.FRAME_HEIGHT
        )
        return

    if args.simulate:
        run_simulate()
        return

    try:
        run_real(args.show)
    except FileNotFoundError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"[错误] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
