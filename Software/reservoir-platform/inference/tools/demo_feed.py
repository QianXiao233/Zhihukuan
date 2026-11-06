"""本地演示数据源：模拟 MQTT broker + 大坝固件。

用途：没有真实硬件时，让决策服务跑在**有数据的**状态，便于观察界面与决策行为。

它做两件事：
1. 在指定端口拉起嵌入式 MQTT broker（amqtt）；
2. 模拟 STM32 固件的完整行为——每秒上报水位、订阅控制指令、并按**简单的
   水池物理**推演水位变化：闸门开着水位下降，全关则缓慢上升（模拟来水）。

水位物理模型（刻意简单，只为演示）
----------------------------------
::

    dLevel/dt = inflow - gate_count * outflow_per_gate

其中 ``inflow`` 是模拟来水，``outflow_per_gate`` 是单门排水速率。
真实系统的排水量与水位差成非线性关系（托里拆利定律），这里用线性近似，
因为它对"看决策行为"这个目的已经足够，而且参数直观、好调。

运行::

    python tools/demo_feed.py --port 1883
    python tools/demo_feed.py --port 18830 --speed 3   # 加速演示

按 Ctrl+C 停止。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import signal
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 水位物理参数（米 / 秒）
#
# 现场是：1~4 号闸门**放水**（水位下降），5~6 号回抽泵把水送回水箱。
# 演示环境没有真实水箱，用一个"来水 vs 放水"的简单平衡来模拟：
# 全关时水位缓慢上涨（模拟上游持续来水），开闸后下降更快。
#
# 参数标定依据（关键）：
#   一次开闸确认后的保持期是 5 帧 × 1.5 秒 = 7.5 秒。
#   如果 4 门全开 7.5 秒就把水位砸回正常区，AI 会立刻关闸，
#   水位随即重新上涨 → 形成"开-关-开"的振荡，演示看起来像故障。
#   所以这里把单门排水速率控制在「4 门开 7.5 秒约降 0.05m」，
#   使一次保持期内水位只缓慢下移，能观察到完整的调节过程而非抖动。
#
#   稳态校验：全关 60 秒涨 INFLOW*60 = 0.21m；开 1 门 60 秒净降
#   (OUTFLOW-INFLOW)*60 = 0.03m —— 两者都在合理量级。
INFLOW_RATE = 0.0035
"""模拟来水：全关时水位上升速度（米/秒）"""

OUTFLOW_PER_GATE = 0.0025
"""单个闸门的放水速率（米/秒），已按决策保持期标定，避免水位振荡"""

START_LEVEL = 0.55
MIN_LEVEL = 0.10
MAX_LEVEL = 1.35
"""上限设 1.35 而不是 2.0：一旦越过 1.20 应急线，AI 会持续要求全开，
演示会卡在同一个状态上，看不到完整的调节过程。"""


class SimulatedDam:
    """水池模型：按当前开着的门数推演水位变化。"""

    def __init__(self, level: float = START_LEVEL) -> None:
        self.level = level
        self.relays = [0] * 8
        self._last_tick = time.monotonic()

    @property
    def open_gates(self) -> int:
        return sum(1 for v in self.relays[:4] if v)

    def tick(self) -> float:
        """推进时间，返回新水位。"""
        now = time.monotonic()
        dt = max(0.0, min(now - self._last_tick, 5.0))  # 防止长时间挂起后跳变
        self._last_tick = now

        # 排水量与开着的门数成正比；门全关时只有来水
        outflow = self.open_gates * OUTFLOW_PER_GATE
        delta = (INFLOW_RATE - outflow) * dt

        # 加一点噪声，让曲线看起来更真实，也顺带测试模型的抗噪能力
        delta += random.gauss(0, 0.0008)

        self.level = max(MIN_LEVEL, min(MAX_LEVEL, self.level + delta))
        return self.level

    def apply_command(self, data: dict) -> bool:
        """处理固件风格的 relay.set 指令。"""
        if data.get("cmd") != "relay.set":
            return False
        relay = data.get("relay")
        state = data.get("state")
        if not isinstance(relay, int) or not isinstance(state, int):
            return False
        if not (1 <= relay <= 8) or state not in (0, 1):
            return False
        if self.relays[relay - 1] != state:
            self.relays[relay - 1] = state
            return True
        return False


class BrokerThread:
    """在后台事件循环里跑 amqtt broker（同 tests/e2e_mqtt.py 的做法）。"""

    def __init__(self, port: int) -> None:
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._broker = None
        self.error: str | None = None

    def start(self, timeout: float = 20.0) -> None:
        ready = threading.Event()

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            try:
                from amqtt.broker import Broker
            except ImportError:
                self.error = "缺少 amqtt，请执行: pip install amqtt"
                ready.set()
                return

            config = {
                "listeners": {
                    # 现场固件走 TCP 1883
                    "default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"},
                    # 浏览器只能连 WebSocket；前端 mqttUrl() 默认 ws://<域名>/mqtt，
                    # 本地由 Vite 把 /mqtt 反代到这里的 8083
                    "ws": {"type": "ws", "bind": "127.0.0.1:8083", "max_connections": 20},
                },
                "sys_interval": 0,
                "auth": {"allow-anonymous": True},
                "plugins": {
                    "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True},
                },
            }

            async def boot():
                # Broker() 必须在运行中的 loop 内构造
                self._broker = Broker(config)
                await self._broker.start()

            try:
                loop.run_until_complete(boot())
            except Exception as exc:
                self.error = f"broker 启动失败: {exc}"
                ready.set()
                return
            ready.set()
            loop.run_forever()

        threading.Thread(target=runner, daemon=True, name="demo-broker").start()
        if not ready.wait(timeout):
            raise RuntimeError("broker 启动超时")

    def stop(self) -> None:
        if self._loop is None or self._broker is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broker.shutdown(), self._loop).result(timeout=10)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="本地演示：模拟 broker + 大坝固件")
    parser.add_argument("--port", type=int, default=1883, help="broker 端口")
    parser.add_argument("--interval", type=float, default=1.5, help="上报间隔（秒）")
    parser.add_argument("--start-level", type=float, default=START_LEVEL)
    parser.add_argument("--noise", action="store_true", help="注入随机扰动（演示抗干扰）")
    args = parser.parse_args()

    import paho.mqtt.client as mqtt

    print("=" * 60)
    print("本地演示数据源")
    print("=" * 60)

    broker = BrokerThread(args.port)
    broker.start()
    if broker.error:
        print(f"[!] {broker.error}")
        return 2
    print(f"[1/2] broker 已启动 127.0.0.1:{args.port}")

    dam = SimulatedDam(args.start_level)

    client = mqtt.Client(
        client_id="DemoFirmware",
        protocol=mqtt.MQTTv311,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )

    def on_connect(c, userdata, flags, rc, properties=None):
        if rc == 0:
            c.subscribe("rtu/control", qos=1)
            print("[2/2] 模拟固件已连接，订阅 rtu/control")
            print()
            print(f"       初始水位 {dam.level:.3f} m，每 {args.interval}s 上报一次")
            print("       按 Ctrl+C 停止")
            print("-" * 60)

    def on_message(c, userdata, msg):
        try:
            data = json.loads(msg.payload.decode())
        except Exception:
            return
        if dam.apply_command(data):
            opened = [i for i, v in enumerate(dam.relays[:4]) if v]
            print(f"   [指令] relay={data['relay']} state={data['state']}"
                  f" → 已开 {len(opened)} 门 {opened}")

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect("127.0.0.1", args.port, keepalive=60)
    client.loop_start()

    stop = threading.Event()

    def handle_signal(signum, frame):
        stop.set()

    try:
        signal.signal(signal.SIGINT, handle_signal)
    except Exception:
        pass

    last_report = 0.0
    try:
        while not stop.is_set():
            level = dam.tick()
            now = time.monotonic()
            if now - last_report >= args.interval:
                last_report = now
                payload = json.dumps({
                    "relay": dam.relays,
                    "temp": round(24.5 + random.uniform(-0.3, 0.3), 1),
                    "level": round(level, 4),
                    "ph": round(7.2 + random.uniform(-0.05, 0.05), 2),
                    "orp": 120,
                }, separators=(",", ":"))
                client.publish("rtu/status", payload, qos=1)
                opened = [i for i, v in enumerate(dam.relays[:4]) if v]
                bar = "█" * int(level * 30)
                print(f"   {level:.3f} m |{bar:<36}| 开{len(opened)}门 {opened}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[清理]")
        client.loop_stop()
        client.disconnect()
        broker.stop()
        print("   已停止")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
