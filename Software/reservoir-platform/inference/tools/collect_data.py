"""数据采集器：订阅 MQTT 水位，自动标注动作，产出世界模型训练集。

迁移自智慧大坝的 ``data_collector_websocket.py``（及其备份 ``beifen.py``），
数据源由原来的 ``ws://192.168.10.251:8085`` + HTTP 闸门控制
改为平台统一的 MQTT（上行 ``rtu/status``、下行 ``rtu/control``）。

采集策略（沿用原型意图）
------------------------
原型的目的是「覆盖全水位区间」：开闸让水位掉到低位，再加水抬到高位，
在不同区间反复扫，让世界模型见到足够多样的 (水位, 动作) → 下一水位 组合。
这里保留随机加水目标，但把坐标换成平台单位（米）。

输出格式与 ``tools/train_model.py`` 完全对齐::

    np.array([{'water_history': [...], 'action_history': [...], 'next_water': ...}, ...],
             dtype=object)

用法::

    python tools/collect_data.py --seconds 600 --out data/training_data.npy
    python tools/collect_data.py --seconds 60 --out data/test.npy --dry-run
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import threading
import time
from pathlib import Path

import numpy as np
import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mqtt_client import build_relay_command, parse_status  # noqa: E402


class Collector:
    """把 MQTT 读数流切成 (历史窗口, 下一帧) 样本。

    只在「历史窗口已满」时产出样本，且每个新读数都产出一条——
    相邻样本高度重叠是正常的：训练目标是单步预测，重叠能提高数据利用率。
    """

    def __init__(self, history_len: int, scale: float = 1.0) -> None:
        self.history_len = history_len
        self.scale = scale
        self.water_hist: list[float] = []
        self.action_hist: list[int] = []
        self.samples: list[dict[str, object]] = []
        self.current_action = 0
        self.lock = threading.Lock()

    def feed(self, water: float) -> dict[str, object] | None:
        """喂一帧水位，返回新产出的样本（没有则 ``None``）。

        动作历史里记录的是「上一帧执行的动作」——因为动作影响的是**下一次**的水位变化，
        这一点与原型的 data_collector 一致。
        """
        with self.lock:
            sample = None
            if len(self.water_hist) >= self.history_len:
                sample = {
                    "water_history": [round(w, 4) for w in self.water_hist[-self.history_len:]],
                    "action_history": list(self.action_hist[-self.history_len:]),
                    "next_water": round(water, 4),
                }
                # 存成模型刻度，避免下游再换算
                sample["water_history"] = [w * self.scale for w in sample["water_history"]]
                sample["next_water"] = sample["next_water"] * self.scale
                self.samples.append(sample)

            self.water_hist.append(water)
            self.action_hist.append(self.current_action)
            return sample


def main() -> int:
    parser = argparse.ArgumentParser(description="采集世界模型训练数据")
    parser.add_argument("--broker", default="tcp://127.0.0.1:1883")
    parser.add_argument("--status-topic", default="rtu/status")
    parser.add_argument("--control-topic", default="rtu/control")
    parser.add_argument("--relay", type=int, default=1, help="受控闸门编号 1..8")
    parser.add_argument("--seconds", type=int, default=600, help="采集时长（秒）")
    parser.add_argument("--history-len", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("data/training_data.npy"))
    parser.add_argument("--scale", type=float, default=100.0,
                        help="米→模型刻度换算系数，需与训练时一致")
    parser.add_argument("--save-interval", type=int, default=120, help="落盘间隔（秒）")
    parser.add_argument("--dry-run", action="store_true",
                        help="不真正下发闸门指令，只记录读数与假设动作")
    parser.add_argument("--fill-min", type=float, default=0.55,
                        help="随机加水目标下限（米）")
    parser.add_argument("--fill-max", type=float, default=1.10,
                        help="随机加水目标上限（米）")
    args = parser.parse_args()

    collector = Collector(args.history_len, args.scale)
    stop = threading.Event()

    # ── MQTT 设置 ──
    raw = args.broker
    for scheme in ("tcp://", "mqtt://"):
        if raw.startswith(scheme):
            raw = raw[len(scheme):]
            break
    host, _, port_text = raw.partition(":")
    port = int(port_text) if port_text else 1883

    client = mqtt.Client(
        client_id=f"DamCollector{random.randint(1000, 9999)}",
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    connected = threading.Event()
    dispatch_enabled = not args.dry_run

    def send_action(action: int) -> None:
        """下发闸门动作。动作没变就不重复发。"""
        with collector.lock:
            if collector.current_action == action:
                return
            collector.current_action = action
        if not dispatch_enabled:
            return
        payload = build_relay_command(args.relay, action)
        client.publish(args.control_topic, payload, qos=1)
        print(f"   → 下发 {payload}")

    def on_connect(c, userdata, flags, rc, properties=None):
        if rc == 0:
            connected.set()
            c.subscribe(args.status_topic, qos=1)
            print(f"[✓] 已连接 {host}:{port}，订阅 {args.status_topic}")
        else:
            print(f"[!] 连接失败: {rc}")

    def on_message(c, userdata, msg):
        parsed = parse_status(msg.payload)
        if parsed is None or parsed.get("level") is None:
            return
        water = float(parsed["level"])
        collector.feed(water)

    client.on_connect = on_connect
    client.on_message = on_message

    print("=" * 62)
    print("数据采集器")
    print("=" * 62)
    print(f"   时长: {args.seconds}s | 历史窗口: {args.history_len}")
    print(f"   换算: 米 × {args.scale}")
    print(f"   下发指令: {'关闭（dry-run）' if args.dry_run else '开启'}")
    print(f"   输出: {args.out}")

    client.connect_async(host, port, keepalive=60)
    client.loop_start()

    if not connected.wait(timeout=15):
        print("[!] 15 秒内未连上 MQTT，退出")
        client.loop_stop()
        return 2

    # ── 采集循环 ──
    started = time.time()
    last_save = started
    last_fill_target = 0.0
    phase_open = False

    try:
        while not stop.is_set():
            elapsed = time.time() - started
            if elapsed >= args.seconds:
                break

            with collector.lock:
                current = collector.water_hist[-1] if collector.water_hist else None

            if current is not None:
                # 两段式扫水位：先开闸放水把水位压低，再关闸等水位回升
                if not phase_open and current > args.fill_min + 0.05:
                    # 水位偏高 → 开闸放水，制造下降段样本
                    send_action(1)
                    phase_open = True
                elif phase_open and current <= args.fill_min:
                    # 放到底了 → 关闸，等待自然回升或人工加水
                    send_action(0)
                    phase_open = False
                    last_fill_target = random.uniform(args.fill_min, args.fill_max)
                    print(f"   水位 {current:.3f} m 已到低位，关闸等待回升至约 {last_fill_target:.2f} m")

            if time.time() - last_save >= args.save_interval:
                _save(collector, args.out)
                last_save = time.time()

            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n[!] 手动中断")
    finally:
        client.loop_stop()
        client.disconnect()

    _save(collector, args.out)
    print(f"\n采集结束：{len(collector.samples)} 条样本")
    print(f"已保存: {args.out}")
    return 0


def _save(collector: Collector, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with collector.lock:
        data = np.array(collector.samples, dtype=object)
    if len(data) == 0:
        return
    np.save(path, data)
    print(f"   [落盘] {len(data)} 条 → {path.name}")


if __name__ == "__main__":
    raise SystemExit(main())
