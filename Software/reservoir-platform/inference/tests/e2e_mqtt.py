"""端到端验收脚本：在本地拉起 MQTT broker + 模拟固件，跑通完整决策闭环。

它验证的不是单元逻辑，而是**整条链路真的能通**：

    模拟固件 ──上报 rtu/status──▶ 推理服务（决策）──下发 rtu/control──▶ 模拟固件

这能抓出单元测试抓不到的问题：主题名写错、JSON 格式不被固件解析器接受、
paho 版本 API 不兼容、控制开关联动、冷却期在下发侧的表现等。

运行::

    cd Software/reservoir-platform/inference
    python tests/e2e_mqtt.py

脚本自带清理：结束后关闭 broker、停止推理服务、恢复原始环境变量。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BROKER_PORT = 18830
"""用一个不常见的端口，避免和现场真的 broker 撞车。"""


class FakeFirmware:
    """模拟 STM32 固件的 MQTT 行为。

    行为严格对齐 `Core/Src/mqtt_app.c`：
    - 每 1.5 秒发布 `rtu/status`，payload 是 `{"relay":[...8],"temp":..,"level":..,"ph":..,"orp":..}`
    - 订阅 `rtu/control`，收到 `{"cmd":"relay.set","relay":N,"state":S}` 后更新继电器
    """

    def __init__(self, broker_host: str, broker_port: int) -> None:
        import paho.mqtt.client as mqtt

        self.mqtt = mqtt
        self.relays = [0] * 8
        self.received_commands: list[dict] = []
        self._client = mqtt.Client(
            client_id="FakeFirmware",
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._host = broker_host
        self._port = broker_port

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe("rtu/control", qos=1)

    def _on_message(self, client, userdata, msg):
        """按固件的手写解析器逻辑处理：只认 cmd=relay.set，relay 1..8，state 0/1。"""
        try:
            data = json.loads(msg.payload.decode())
        except Exception:
            return
        if data.get("cmd") != "relay.set":
            return
        relay = data.get("relay")
        state = data.get("state")
        if not isinstance(relay, int) or not isinstance(state, int):
            return  # 固件要求整数，字符串会被 json_get_int 拒绝
        if not (1 <= relay <= 8) or state not in (0, 1):
            return
        self.relays[relay - 1] = state
        self.received_commands.append({"relay": relay, "state": state, "at": time.time()})
        print(f"   [固件] 收到控制指令 relay={relay} state={state} -> 继电器={self.relays}")

    def connect(self) -> None:
        self._client.connect(self._host, self._port, keepalive=30)
        self._client.loop_start()

    def publish_status(self, level: float) -> None:
        payload = json.dumps({
            "relay": self.relays,
            "temp": 25.5,
            "level": round(level, 4),
            "ph": 7.2,
            "orp": 120,
        }, separators=(",", ":"))
        self._client.publish("rtu/status", payload, qos=1)

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


class BrokerThread:
    """在后台事件循环里运行 amqtt broker。

    amqtt 0.12 的约束比旧版严格：

    1. ``Broker(...)`` 必须在**正在运行**的 event loop 内构造
       （它内部调用 ``asyncio.get_running_loop()``），
       不能在 ``run_until_complete`` 之前建；
    2. broker 的 IO 依赖那个 loop 持续运转，必须 ``run_forever()``。
       否则 TCP 能 accept，但协议握手永远不推进——
       表现为客户端"连上了却收不到任何消息"，极易误判成代码 bug。

    所以这里起一个独立线程持有一个 loop 并一直跑，
    启动与关闭都用 ``run_coroutine_threadsafe`` 投递进去。
    """

    def __init__(self, port: int) -> None:
        self.port = port
        self._loop: asyncio.AbstractEventLoop | None = None
        self._broker = None
        self._thread: threading.Thread | None = None
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
                self.error = "缺少 amqtt，请先执行: pip install amqtt"
                ready.set()
                return

            config = {
                "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{self.port}"}},
                "sys_interval": 0,
                "auth": {"allow-anonymous": True},
                "plugins": {
                    "amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True},
                },
            }
            try:
                # 关键：Broker() 内部调用 asyncio.get_running_loop()，
                # 只有在协程内部（loop 真正在跑）才拿得到，所以包一层 async 函数
                async def boot():
                    from amqtt.broker import Broker
                    self._broker = Broker(config)
                    await self._broker.start()

                loop.run_until_complete(boot())
            except Exception as exc:
                self.error = f"broker 启动失败: {exc}"
                ready.set()
                return
            ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=runner, daemon=True, name="mqtt-broker")
        self._thread.start()
        if not ready.wait(timeout):
            raise RuntimeError("broker 启动超时")

    def stop(self, timeout: float = 10.0) -> None:
        if self._loop is None or self._broker is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broker.shutdown(), self._loop).result(timeout=timeout)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass


def start_service(port: int, broker_port: int) -> "subprocess.Popen":
    """以子进程启动推理服务，并打开控制下发。"""
    import subprocess

    env = os.environ.copy()
    env.update({
        "MQTT_ENABLED": "true",
        "MQTT_BROKER": f"tcp://127.0.0.1:{broker_port}",
        "AUTO_DECIDE": "true",
        "DISPATCH_CONTROL": "true",   # 本次验收要验证真实下发
        "API_TOKEN": "",
        "PORT": str(port),
    })
    print(f"[启动] 推理服务 port={port}, broker=127.0.0.1:{broker_port}")
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        env=env,
    )


def main() -> int:
    import urllib.request

    service_port = 5099
    broker = None
    firmware = None
    process = None
    failures: list[str] = []

    print("=" * 66)
    print("端到端验收：模拟固件 <-> 推理服务")
    print("=" * 66)

    try:
        # ── 1. broker ──
        print(f"\n[1/5] 启动 broker 127.0.0.1:{BROKER_PORT}")
        broker = BrokerThread(BROKER_PORT)
        broker.start()
        if broker.error:
            print(f"[!] {broker.error}")
            return 2
        print("   broker 已就绪")

        # ── 2. 服务 ──
        print("\n[2/5] 启动推理服务")
        process = start_service(service_port, BROKER_PORT)

        # 等服务就绪
        ready = False
        for _ in range(40):
            time.sleep(1)
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{service_port}/health", timeout=2) as r:
                    if r.status == 200:
                        ready = True
                        break
            except Exception:
                continue
        if not ready:
            print("[!] 服务 40 秒内未就绪")
            return 3
        print("   服务已就绪")

        # ── 3. 固件 ──
        print("\n[3/5] 连接模拟固件")
        firmware = FakeFirmware("127.0.0.1", BROKER_PORT)
        firmware.connect()
        time.sleep(2)

        # ── 4. 喂水位 ──
        print("\n[4/5] 上报水位序列：正常 -> 预警 -> 应急（触发 4 门全开）")
        levels = [0.55, 0.58, 0.61, 0.64, 0.67, 0.70, 0.74, 0.78, 0.82, 0.86,
                  1.22, 1.25, 1.28, 1.31, 1.34, 1.37]
        for i, level in enumerate(levels):
            firmware.publish_status(level)
            print(f"   [第{i + 1}帧] 上报水位 {level} m")
            time.sleep(1.6)  # 略大于固件 1.5 秒的上报间隔

        # ── 5. 检查 ──
        print("\n[5/5] 验收结果")
        with urllib.request.urlopen(f"http://127.0.0.1:{service_port}/api/brain/status", timeout=5) as r:
            status = json.loads(r.read().decode())

        brain = status.get("brain", {})
        gate = brain.get("gate", {})
        gate_array = brain.get("gates", {})
        decision = brain.get("decision") or {}
        mqtt_stats = status.get("mqtt", {})

        print(f"   水位帧接收: {mqtt_stats.get('framesReceived')}")
        print(f"   指令下发数: {mqtt_stats.get('commandsSent')}")
        print(f"   仲裁状态: {gate.get('state')}")
        print(f"   待确认: {gate.get('pending') is not None}")
        print(f"   AI 建议档位: {decision.get('action')} / 容量 {gate_array.get('capacity')}")
        print(f"   固件继电器实际状态: {firmware.relays[:4]}")

        if mqtt_stats.get("framesReceived", 0) < len(levels) - 2:
            failures.append(f"水位帧接收不足：{mqtt_stats.get('framesReceived')} < {len(levels)}")
        if not gate.get("pending"):
            failures.append("应急水位下应处于待确认状态，实际没有")
        if decision.get("action") != gate_array.get("capacity"):
            failures.append(
                f"应急水位应建议全开 {gate_array.get('capacity')} 门，"
                f"实际建议 {decision.get('action')}"
            )
        # 注意：此时**不应**有开闸指令下发——AI 只是"建议"，必须等人工确认。
        # 这正是本系统的安全设计：待确认期间闸门保持全关。
        if any(firmware.relays):
            failures.append(f"待确认期间闸门应保持全关，实际 {firmware.relays[:4]}")

        # ── 5b. 确认开闸，验证 4 路真的下发 ──
        print("\n[5b] 确认开闸，验证多路下发")
        confirm_req = urllib.request.Request(
            f"http://127.0.0.1:{service_port}/api/brain/confirm",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(confirm_req, timeout=10) as r:
            confirmed = json.loads(r.read().decode())

        print(f"   确认结果: accepted={confirmed.get('accepted')} action={confirmed.get('action')}")
        print(f"   下发方案: {confirmed.get('gatePlan')}")
        time.sleep(2.5)

        opened = [i + 1 for i, v in enumerate(firmware.relays[:4]) if v == 1]
        print(f"   固件已开的门: {opened}")

        if not confirmed.get("accepted"):
            failures.append("确认开闸失败")
        if len(opened) != gate_array.get("capacity"):
            failures.append(
                f"确认后应开 {gate_array.get('capacity')} 个门，实际开了 {len(opened)} 个: {opened}"
            )

    except Exception as exc:
        import traceback
        traceback.print_exc()
        failures.append(f"验收过程异常: {exc}")
    finally:
        print("\n[清理]")
        if firmware is not None:
            try:
                firmware.stop()
            except Exception:
                pass
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except Exception:
                process.kill()
            print("   推理服务已停止")
        if broker is not None:
            try:
                broker.stop()
            except Exception:
                pass
            print("   broker 已关闭")

    print("\n" + "=" * 66)
    if failures:
        print("验收失败：")
        for item in failures:
            print(f"  [X] {item}")
        print("=" * 66)
        return 1

    print("验收通过：固件 -> 服务 -> 决策 -> 固件 整条链路可用")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
