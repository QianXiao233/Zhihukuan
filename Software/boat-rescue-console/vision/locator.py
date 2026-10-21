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
    def __init__(self, url: str):
        self.url = url.rstrip("/") + "/api/navigation"
        self.fail_count = 0
        self.ok_count = 0
        self._last_warn = 0.0

    def send(self, boat_x, boat_y, heading, target_x, target_y) -> None:
        payload = json.dumps(
            {
                "boatX": round(boat_x, 4),
                "boatY": round(boat_y, 4),
                "heading": round(heading % 360.0, 2),
                "targetX": round(target_x, 4),
                "targetY": round(target_y, 4),
            }
        ).encode("utf-8")

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

    def release(self) -> None:
        """停止推送，交还控制权给网页。"""
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
def open_camera() -> cv2.VideoCapture:
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
    return cap


def run_real(show: bool) -> None:
    if not HAS_CV2:
        raise RuntimeError("实时定位需要 OpenCV，请先安装: pip install opencv-python")

    from boat import BoatDetector
    from target import TargetDetector

    H = pool_mod.load_calibration()
    boat = BoatDetector(config.ARUCO_ID)
    target = TargetDetector()
    reporter = Reporter(config.SERVER_URL)

    cap = open_camera()
    period = 1.0 / config.REPORT_HZ
    last_report = 0.0
    last_print = 0.0

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

            if pose is None:
                # 丢码时重置航向滤波，避免下次出现时残留旧航向
                boat.reset_filter()

            now = time.time()
            if pose is not None and tgt is not None and (now - last_report) >= period:
                last_report = now
                reporter.send(pose.x, pose.y, pose.heading, tgt.x, tgt.y)

            if now - last_print >= 1.0:
                last_print = now
                b = f"({pose.x:.3f},{pose.y:.3f}) hdg={pose.heading:.1f}°" if pose else "未检测到船"
                t = f"({tgt.x:.3f},{tgt.y:.3f})" if tgt else "未检测到目标"
                print(f"船 {b}   目标 {t}   上报 {reporter.ok_count} ok / {reporter.fail_count} fail")

            if show:
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
    args = ap.parse_args()

    if args.camera is not None:
        config.CAMERA_INDEX = args.camera

    if args.calibrate:
        if not HAS_CV2:
            print("[错误] 标定需要 OpenCV，请先安装: pip install opencv-python", file=sys.stderr)
            sys.exit(1)
        pool_mod.calibrate_interactively(config.CAMERA_INDEX)
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
