"""配置：全部来自环境变量，带与平台一致的默认值。

单位约定：本服务对外一律使用 **米**，与平台 ``dam_system_param`` 保持一致。
模型内部的原始刻度换算由 ``brain.world_model.WaterScale`` 负责。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# config.py 就位于 inference/ 根目录，服务根即它所在目录
SERVICE_DIR = Path(__file__).resolve().parent


def _env_str(key: str, default: str) -> str:
    value = os.environ.get(key)
    return value if value not in (None, "") else default


def _env_float(key: str, default: float) -> float:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    raw = os.environ.get(key)
    if raw in (None, ""):
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class MqttConfig:
    """MQTT 接入配置，与平台 ``reservoir.platform.mqtt`` 保持同一套默认值。"""

    enabled: bool = True
    broker: str = "tcp://127.0.0.1:1883"
    client_id: str = "DamBrain"
    username: str = ""
    password: str = ""
    status_topic: str = "rtu/status"
    control_topic: str = "rtu/control"
    qos: int = 1
    keepalive: int = 60
    # 参与协调的闸门数量（现场 4 个：继电器 1~4）
    gate_count: int = 4
    # 单门操作时的默认继电器（保留给人工单门控制）
    gate_relay: int = 1

    @classmethod
    def from_env(cls) -> "MqttConfig":
        return cls(
            enabled=_env_bool("MQTT_ENABLED", True),
            broker=_env_str("MQTT_BROKER", "tcp://127.0.0.1:1883"),
            client_id=_env_str("MQTT_CLIENT_ID", "DamBrain"),
            username=_env_str("MQTT_USERNAME", ""),
            password=_env_str("MQTT_PASSWORD", ""),
            status_topic=_env_str("MQTT_TOPIC", "rtu/status"),
            control_topic=_env_str("MQTT_CONTROL_TOPIC", "rtu/control"),
            qos=_env_int("MQTT_QOS", 1),
            keepalive=_env_int("MQTT_KEEPALIVE", 60),
            gate_count=_env_int("GATE_COUNT", 4),
            gate_relay=_env_int("GATE_RELAY", 1),
        )


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 5001
    # 给 Java 侧的共享密钥；为空表示不校验（仅限内网）
    api_token: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    # 站点名，出现在总线事件的待确认请求里，便于运维知道是哪座坝
    station_name: str = "水库监测站"

    @classmethod
    def from_env(cls) -> "ServerConfig":
        raw = _env_str("CORS_ORIGINS", "*")
        return cls(
            host=_env_str("HOST", "0.0.0.0"),
            port=_env_int("PORT", 5001),
            api_token=_env_str("API_TOKEN", ""),
            cors_origins=[o.strip() for o in raw.split(",") if o.strip()],
            station_name=_env_str("STATION_NAME", "水库监测站"),
        )


@dataclass
class InferenceConfig:
    checkpoint: Path = SERVICE_DIR / "models" / "world_model.pt"
    autosave_dir: Path = SERVICE_DIR / "data" / "checkpoints"
    autosave_every: int = 200

    # 米 → 模型原始刻度的换算系数
    scale_factor: float = 100.0
    scale_offset: float = 0.0

    # 是否在启动后自动开始决策（否则只提供 /decide 手动调用）
    auto_decide: bool = True

    # 是否真的把开闸/关闸指令发到 MQTT。
    # 默认 False：首次接入时先只观察决策，确认逻辑正确后再打开，
    # 避免误动作真实闸门。这是有意保守的默认值。
    dispatch_control: bool = False

    mqtt: MqttConfig = field(default_factory=MqttConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    @classmethod
    def from_env(cls) -> "InferenceConfig":
        return cls(
            checkpoint=Path(_env_str("MODEL_PATH", str(SERVICE_DIR / "models" / "world_model.pt"))),
            autosave_dir=Path(_env_str("AUTOSAVE_DIR", str(SERVICE_DIR / "data" / "checkpoints"))),
            autosave_every=_env_int("AUTOSAVE_EVERY", 200),
            scale_factor=_env_float("WATER_SCALE_FACTOR", 100.0),
            scale_offset=_env_float("WATER_SCALE_OFFSET", 0.0),
            auto_decide=_env_bool("AUTO_DECIDE", True),
            dispatch_control=_env_bool("DISPATCH_CONTROL", False),
            mqtt=MqttConfig.from_env(),
            server=ServerConfig.from_env(),
        )
