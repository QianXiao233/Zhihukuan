"""MQTT 客户端：订阅水位、下发闸门指令。

替换了原型的两种数据接入方式（裸 TCP 二进制帧 `AA11…DBBB`、以及 WebSocket +
HTTP `/RelayControl/Open`）。现在统一走平台既有的 MQTT：

* **上行** ``rtu/status`` —— 固件每 1.5 s 上报一次
  ``{"relay":[8 个 0/1],"temp":..,"level":..,"ph":..,"orp":..}``
* **下行** ``rtu/control`` —— 发送 ``{"cmd":"relay.set","relay":N,"state":0|1}``

协议细节来自固件 ``Core/Src/mqtt_app.c``：
``dispatch_command`` 只识别 ``relay.set`` 与 ``config.set``，JSON 解析是轻量的整数提取，
所以字段顺序无关、但**必须存在且为整数**，且 ``relay`` 必须落在 1..8。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import paho.mqtt.client as mqtt

from config import MqttConfig

log = logging.getLogger(__name__)

# 固件里的继电器总数（devices.h: RELAY_COUNT 8）
RELAY_COUNT = 8


def parse_status(payload: bytes) -> dict[str, object] | None:
    """解析固件上报。

    返回 ``None`` 表示这条报文不可用（JSON 损坏、或没有任何有效测量值的心跳帧）。
    心跳帧在水位为空时也会到达，必须跳过，否则会把 ``None`` 当成 0 米喂给模型。
    """
    try:
        data = json.loads(payload.decode("utf-8", errors="ignore"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None

    level = data.get("level")
    # 固件在传感器无效时会发字符串 "null"
    if level is None or isinstance(level, str):
        level_val = None
    else:
        try:
            level_val = float(level)
        except (TypeError, ValueError):
            level_val = None

    relays_raw = data.get("relay")
    relays: list[int] = []
    if isinstance(relays_raw, list):
        for item in relays_raw[:RELAY_COUNT]:
            try:
                relays.append(int(item))
            except (TypeError, ValueError):
                relays.append(0)
    while len(relays) < RELAY_COUNT:
        relays.append(0)

    # 四项测量全空 = 心跳/占位帧，丢弃
    others = [data.get(k) for k in ("temp", "ph", "orp")]
    if level_val is None and all(o is None or isinstance(o, str) for o in others):
        return None

    return {
        "level": level_val,
        "relays": relays,
        "temperature": data.get("temp"),
        "ph": data.get("ph"),
        "orp": data.get("orp"),
    }


def build_relay_command(relay: int, state: int) -> str:
    """构造固件能识别的控制报文。字段必须都是整数，``cmd`` 必须是 ``relay.set``。

    失败安全：只有明确的 ``state == 1`` 才编码为开闸，其余任何值（含 2、7、负数）
    都编码为关闸。开闸是物理动作，取值异常时宁可少开也不能误开。
    """
    relay = max(1, min(RELAY_COUNT, int(relay)))
    normalized = 1 if int(state) == 1 else 0
    return json.dumps({"cmd": "relay.set", "relay": relay, "state": normalized}, separators=(",", ":"))


class MqttBridge:
    """MQTT 桥：维护连接、订阅上报、发布控制。

    回调全部在 paho 的网络线程里执行，因此 ``on_level`` 里的重活（模型推理）
    必须足够快，或自行丢到线程池。本服务推理是毫秒级（48~66 个候选，
    每个 10 步自回归），实测单帧总耗时远小于固件 1.5 s 的上报间隔，直接同步处理即可。
    """

    def __init__(
        self,
        cfg: MqttConfig,
        on_level: Callable[[float, dict[str, object]], None],
        dispatch_enabled: bool = False,
    ) -> None:
        self.cfg = cfg
        self.on_level = on_level
        self.dispatch_enabled = dispatch_enabled

        self._client: mqtt.Client | None = None
        self._connected = threading.Event()
        self._stop = threading.Event()

        self.frames_received = 0
        self.frames_dropped = 0
        self.commands_sent = 0
        self.last_error: str | None = None
        self.last_level_at: float | None = None
        self.last_command: dict[str, object] | None = None

        # 记住上一路闸门状态，避免每帧重复下发同一条指令
        self._last_relay_state: dict[int, int] = {}

    # ── 连接管理 ──────────────────────────────────────────────

    def start(self) -> None:
        if not self.cfg.enabled:
            log.info("MQTT 已禁用（MQTT_ENABLED=false），仅提供手动 /decide 接口")
            return

        host, port = self._parse_broker(self.cfg.broker)
        client = mqtt.Client(
            client_id=self.cfg.client_id,
            protocol=mqtt.MQTTv311,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        if self.cfg.username:
            client.username_pw_set(self.cfg.username, self.cfg.password or None)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        self._client = client
        log.info("连接 MQTT broker %s:%d，订阅 %s", host, port, self.cfg.status_topic)
        try:
            client.connect_async(host, port, keepalive=self.cfg.keepalive)
            client.loop_start()
        except Exception as exc:
            self.last_error = str(exc)
            log.error("MQTT 启动失败: %s", exc)

    def stop(self) -> None:
        self._stop.set()
        if self._client is not None:
            try:
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:
                pass
            self._client = None
        log.info("MQTT 已停止")

    @staticmethod
    def _parse_broker(broker: str) -> tuple[str, int]:
        """支持 ``tcp://host:port`` 与裸 ``host:port`` 两种写法。"""
        raw = broker
        for scheme in ("tcp://", "mqtt://"):
            if raw.startswith(scheme):
                raw = raw[len(scheme):]
                break
        if ":" in raw:
            host, port_text = raw.rsplit(":", 1)
            try:
                return host, int(port_text)
            except ValueError:
                return raw, 1883
        return raw, 1883

    # ── paho 回调 ─────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code == 0:
            self._connected.set()
            self.last_error = None
            client.subscribe(self.cfg.status_topic, qos=self.cfg.qos)
            log.info("MQTT 已连接，订阅 %s", self.cfg.status_topic)
        else:
            self.last_error = f"连接被拒绝: {reason_code}"
            log.warning("MQTT 连接失败: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None) -> None:
        self._connected.clear()
        if not self._stop.is_set():
            log.warning("MQTT 连接断开（%s），paho 将自动重连", reason_code)

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            parsed = parse_status(msg.payload)
        except Exception as exc:
            self.frames_dropped += 1
            log.debug("解析上报失败: %s", exc)
            return

        if parsed is None:
            self.frames_dropped += 1
            return

        level = parsed.get("level")
        if level is None:
            self.frames_dropped += 1
            return

        self.frames_received += 1
        self.last_level_at = time.time()
        try:
            self.on_level(float(level), parsed)
        except Exception as exc:
            # 回调异常绝不能抛回 paho 的网络线程，否则连接会被断开
            self.last_error = f"处理水位失败: {exc}"
            log.exception("处理水位回调异常")

    # ── 指令下发 ──────────────────────────────────────────────

    def set_relay(self, state: int, relay: int | None = None) -> bool:
        """设置**单路**继电器状态。

        :param state: 1=开，0=关
        :param relay: 继电器编号 1..8；省略时用配置里的 ``gate_relay``
        :return: 是否真的发出（受 ``dispatch_control`` 与连接状态约束）
        """
        relay = relay if relay is not None else self.cfg.gate_relay
        return self.apply_relays({relay: 1 if int(state) == 1 else 0}) > 0

    def apply_relays(self, desired: dict[int, int]) -> int:
        """批量下发多路继电器的目标状态。

        与 :meth:`set_relay` 的区别是它能**一次调用变更多路**，且只发真正
        需要变化的那些——协调器给的 ``plan`` 天然就是这个形态
        （``{"open": [2,3], "close": [1]}`` 转换成 ``{2:1, 3:1, 1:0}``）。

        :return: 实际成功下发的路数
        """
        if not desired:
            return 0

        # 先算出真正需要变化的路
        changes: dict[int, int] = {}
        for relay, state in desired.items():
            relay = max(1, min(RELAY_COUNT, int(relay)))
            state = 1 if int(state) == 1 else 0
            if self._last_relay_state.get(relay) != state:
                changes[relay] = state

        if not changes:
            return 0

        if not self.dispatch_enabled:
            log.info(
                "闸门指令被抑制（DISPATCH_CONTROL=false）: %s",
                ", ".join(f"#{r}={s}" for r, s in sorted(changes.items())),
            )
            # 即使被抑制也要记账，避免每帧重复打印日志
            self._last_relay_state.update(changes)
            return 0

        if self._client is None or not self._connected.is_set():
            self.last_error = "MQTT 未连接，指令未下发"
            log.warning("闸门指令未下发：MQTT 未连接")
            return 0

        sent = 0
        for relay, state in sorted(changes.items()):
            payload = build_relay_command(relay, state)
            try:
                info = self._client.publish(self.cfg.control_topic, payload, qos=self.cfg.qos)
                if info.rc != mqtt.MQTT_ERR_SUCCESS:
                    self.last_error = f"publish 失败 rc={info.rc}"
                    log.warning("闸门 #%d 指令发布失败 rc=%s", relay, info.rc)
                    continue
            except Exception as exc:
                self.last_error = str(exc)
                log.error("闸门 #%d 指令异常: %s", relay, exc)
                continue

            self._last_relay_state[relay] = state
            sent += 1
            log.info("已下发闸门指令: %s", payload)

        if sent:
            self.commands_sent += sent
            self.last_command = {
                "changes": changes,
                "at": time.time(),
                "count": sent,
            }

        return sent

    def apply_plan(self, plan: dict[str, list[int]]) -> int:
        """协调器 ``plan`` 的直接落地。

        ``plan`` 形如 ``{"open": [2,3], "close": [1]}``，转换后批量下发。
        """
        desired: dict[int, int] = {}
        for gate_id in plan.get("close", []):
            desired[int(gate_id)] = 0
        for gate_id in plan.get("open", []):
            desired[int(gate_id)] = 1
        return self.apply_relays(desired)

    # ── 指令确认窗口 ──────────────────────────────────────────

    ACK_WINDOW_SECONDS = 4.0
    """下发指令后，等待固件上报反映新状态的窗口（秒）。

    固件每 1.5 秒上报一次，留 4 秒足够覆盖一次上报周期加网络抖动。
    窗口内不采信上报的继电器状态做内部校正，避免把刚下发的"已开"
    覆盖回"未开"而导致重复下发（表现为闸门连续开关）。
    """

    def has_recent_commands(self) -> bool:
        """最近是否刚下发过指令（还在等固件上报确认）。"""
        last_at = (self.last_command or {}).get("at")
        if not last_at:
            return False
        return (time.time() - float(last_at)) < self.ACK_WINDOW_SECONDS

    # ── 观测 ──────────────────────────────────────────────────

    def stats(self) -> dict[str, object]:
        return {
            "enabled": self.cfg.enabled,
            "connected": self._connected.is_set(),
            "broker": self.cfg.broker,
            "statusTopic": self.cfg.status_topic,
            "controlTopic": self.cfg.control_topic,
            "dispatchEnabled": self.dispatch_enabled,
            "framesReceived": self.frames_received,
            "framesDropped": self.frames_dropped,
            "commandsSent": self.commands_sent,
            "lastLevelAt": self.last_level_at,
            "lastError": self.last_error,
            "lastCommand": self.last_command,
        }
