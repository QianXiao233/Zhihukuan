"""智御安澜 · 智慧大坝决策大脑 HTTP 服务。

取代原型的 Flask（``/status`` ``/confirm_open`` ``/reject_open``），
接口语义保持一致，但补齐了平台接入所需的鉴权、健康检查与手动决策。

启动::

    python -m uvicorn server:app --host 0.0.0.0 --port 5001

接口一览
--------
============================  ======  ============================================
路径                          方法    说明
============================  ======  ============================================
``/health``                   GET     健康检查（不鉴权，供容器探针使用）
``/api/brain/status``         GET     完整运行状态：水位、闸门、学习、模型、MQTT
``/api/brain/decide``         POST    手动喂一帧水位并返回仲裁结果（调试/回放用）
``/api/brain/confirm``        POST    确认开闸
``/api/brain/reject``         POST    拒绝开闸并进入冷却
``/api/brain/reset``          POST    复位历史与闸门状态
``/api/brain/control``        POST    人工直接控制闸门（绕过 AI，急停用）
============================  ======  ============================================
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from brain import BrainConfig, DamBrain, WaterScale
from brain.gates import CoordinationConfig
from bus_client import BusClient, BusConfig
from config import InferenceConfig
from mqtt_client import MqttBridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("server")

cfg = InferenceConfig.from_env()
brain: DamBrain | None = None
bridge: MqttBridge | None = None
bus: BusClient | None = None


# ══════════════════════════════════════════════════════════════
# 生命周期
# ══════════════════════════════════════════════════════════════

def _handle_level(level: float, parsed: dict[str, Any]) -> None:
    """MQTT 上行 → 决策 → 指令下发。

    这是**唯一**的动作路径：Python 服务直接控制 MQTT，不经过 Java 后端。
    """
    if brain is None:
        return

    # 用固件上报的真实继电器状态校正内部记录。
    #
    # 必须在 observe 之前、且只在**没有刚下发过的指令待确认**时同步：
    # 固件是每 1.5 秒上报一次当前状态，我们下发指令后它要到下一帧才反映。
    # 如果在这中间无条件同步，会把刚下发成功的「已开」覆盖回「未开」，
    # 下一轮协调又以为门关着，于是重复下发——表现为闸门反复开关。
    relays = parsed.get("relays")
    if isinstance(relays, list):
        bridge_ref = bridge
        pending_ack = bridge_ref.has_recent_commands() if bridge_ref else False
        if not pending_ack:
            brain.gates.sync_from_report(relays)

    result = brain.observe(level)
    if result is None:
        return

    # 按协调器给出的最小变更方案下发，只动真正需要变的门
    plan = result.get("gatePlan") or {}
    if plan and bridge is not None:
        sent = bridge.apply_plan(plan)
        if sent:
            # 下发成功后才提交内部状态——先记账会导致状态与真实闸门不一致
            import time as _time
            brain.gates.commit(plan, now=_time.monotonic())

    # 阈值越界或需要确认时：走**服务接入总线**上报，而不是让前端轮询。
    #
    # 为什么：这是"需要人处理的任务"，要落库、要有投递保证、要能审计。
    # 实时状态（水位/闸门）才走直连网关，两者不应混用同一条通道。
    if result["needsConfirmation"]:
        pending = result["gate"].get("pending") or {}
        log.warning(
            "需要人工确认开闸（建议 %d 个门）：水位 %.3f m（%s）— %s",
            pending.get("requestedLevel", 0),
            result["water"], result["level"], result["decision"]["explanation"],
        )
        bus_ref = bus
        if bus_ref is not None:
            bus_ref.publish_pending({
                **pending,
                # 让前端知道是谁该处理：站点 + 水位 + 建议档位
                "stationName": cfg.server.station_name,
                "suggestedLevel": pending.get("requestedLevel"),
                "gateCount": brain.gates.capacity,
            })


@asynccontextmanager
async def lifespan(app: FastAPI):
    global brain, bridge, bus

    log.info("启动决策大脑，检查点=%s", cfg.checkpoint)
    brain = DamBrain(
        cfg.checkpoint,
        scale=WaterScale(cfg.scale_factor, cfg.scale_offset),
        coordination=CoordinationConfig(gate_count=cfg.mqtt.gate_count),
        config=BrainConfig(
            autosave_every=cfg.autosave_every,
            autosave_dir=cfg.autosave_dir,
        ),
    )

    # 服务接入总线：只用于上报"待确认开闸请求"这类需要人处理的任务
    bus = BusClient(BusConfig.from_env())

    bridge = MqttBridge(cfg.mqtt, on_level=_handle_level, dispatch_enabled=cfg.dispatch_control)
    if cfg.auto_decide:
        bridge.start()
    else:
        log.info("AUTO_DECIDE=false，不自动订阅，仅响应手动 /decide")

    log.info(
        "服务就绪 | 端口=%d | 闸门数=%d | 控制下发=%s | 总线=%s | 单位换算=米×%.0f",
        cfg.server.port, cfg.mqtt.gate_count,
        "开启" if cfg.dispatch_control else "关闭（仅观察）",
        "已接入" if bus.cfg.enabled else "未配置",
        cfg.scale_factor,
    )

    try:
        yield
    finally:
        if bridge is not None:
            bridge.stop()
        log.info("服务已停止")


app = FastAPI(
    title="智慧大坝决策大脑",
    description="LSTM 世界模型 + MPC 规划 + 在线学习的闸门决策服务",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.server.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════
# 鉴权
# ══════════════════════════════════════════════════════════════

def require_token(authorization: str | None = Header(default=None)) -> None:
    """共享密钥校验。

    ``API_TOKEN`` 为空时跳过校验——这是内网直连的开发默认，
    正式部署必须配置，防止任意客户端触发开闸。
    """
    if not cfg.server.api_token:
        return
    expected = cfg.server.api_token
    provided = (authorization or "").strip()
    if provided.lower().startswith("bearer "):
        provided = provided[7:].strip()
    if provided != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="鉴权失败")


# ══════════════════════════════════════════════════════════════
# 请求模型
# ══════════════════════════════════════════════════════════════

class DecideRequest(BaseModel):
    water: float = Field(..., ge=0.0, le=5.0, description="当前水位（米）")


class RejectRequest(BaseModel):
    reason: str = Field(default="", max_length=200, description="拒绝原因，仅用于记录")
    requestId: str | None = Field(
        default=None,
        description="待确认请求 id，用于拒绝迟到/重放的请求",
    )


class ControlRequest(BaseModel):
    state: int = Field(..., ge=0, le=8, description="1=开闸（或按 level 指定门数），0=关闸")
    level: int | None = Field(
        default=None, ge=1, le=8,
        description="要开启的闸门数；省略时用 state 的值",
    )
    relay: int | None = Field(
        default=None, ge=1, le=8,
        description="指定单路继电器编号，用于单独控制某一扇门（检修用）",
    )


class ResetRequest(BaseModel):
    clearCooldowns: bool = Field(
        default=False,
        description="是否同时清除拒绝/开闸冷却。默认否：冷却是设备保护，不应被软件复位抹掉",
    )


class ConfirmRequest(BaseModel):
    level: int | None = Field(
        default=None,
        ge=1,
        le=8,
        description="确认时指定开启的闸门数。省略则按 AI 建议的档位执行",
    )
    requestId: str | None = Field(
        default=None,
        description="待确认请求 id。用于拒绝迟到/重放的确认（总线是 at-least-once）",
    )


# ══════════════════════════════════════════════════════════════
# 接口
# ══════════════════════════════════════════════════════════════

@app.get("/health")
def health() -> dict[str, Any]:
    """容器探针用：只要进程起来就返回 ok，不依赖模型是否预热完成。"""
    return {
        "status": "ok",
        "ready": brain is not None and brain.status()["ready"],
        "mqtt": bridge.stats() if bridge else None,
    }


@app.get("/api/brain/status", dependencies=[Depends(require_token)])
def get_status() -> dict[str, Any]:
    """完整状态快照。原 Flask ``/status`` 的超集，字段名与原型保持兼容。"""
    if brain is None:
        raise HTTPException(status_code=503, detail="大脑尚未初始化")

    snap = brain.status()
    gate = snap["gate"]
    pending = gate.get("pending")
    gate_state = snap.get("gates", {})

    return {
        # 原型兼容字段
        "pending_open": gate["state"] == "pending",
        "confirm_flag": 1 if gate["state"] == "opening" else 0,
        "water": pending["water"] if pending else None,
        "level": pending["level"] if pending else None,
        "explanation": pending["explanation"] if pending else None,
        "current_water": snap["water"],
        "current_action": f"开 {gate_state.get('currentLevel', 0)} 门"
        if gate_state.get("currentLevel", 0) > 0 else "关闸",
        "step_count": snap["step"],
        "avg_error": snap["learning"]["averageError"],
        "mode": "inference-service v1",
        # 平台接入字段
        "brain": snap,
        "mqtt": bridge.stats() if bridge else None,
    }


@app.post("/api/brain/decide", dependencies=[Depends(require_token)])
def decide(req: DecideRequest) -> dict[str, Any]:
    """手动喂一帧水位。用于联调、回放与离线验证。"""
    if brain is None:
        raise HTTPException(status_code=503, detail="大脑尚未初始化")

    result = brain.observe(req.water)
    if result is None:
        return {
            "accepted": False,
            "reason": "非法水位或历史窗口未满（预热期）",
            "status": brain.status()["history"],
        }

    plan = result.get("gatePlan") or {}
    if plan and bridge is not None:
        if bridge.apply_plan(plan):
            import time as _time
            brain.gates.commit(plan, now=_time.monotonic())

    return {"accepted": True, **result}


@app.post("/api/brain/confirm", dependencies=[Depends(require_token)])
def confirm(req: ConfirmRequest | None = None) -> dict[str, Any]:
    """确认开闸。

    可选的 ``level`` 允许运维调整档位——AI 建议开 3 个门，现场判断只开 1 个
    也是合理的，强制只能"全盘接受"会让人干脆点拒绝。

    ``requestId`` 用于拒绝过期的迟到确认：总线至少一次投递，同一条待确认
    请求可能被重放；若不做校验，已经处理过的请求可能在无人知情时再开一次闸。
    """
    if brain is None:
        raise HTTPException(status_code=503, detail="大脑尚未初始化")

    level = req.level if req else None
    request_id = req.requestId if req else None
    result = brain.confirm_open(level, request_id)

    if result.get("accepted"):
        plan = result.get("gatePlan") or {}
        if plan and bridge is not None:
            if bridge.apply_plan(plan):
                import time as _time
                brain.gates.commit(plan, now=_time.monotonic())
        # 处理结果回写总线，留下审计痕迹（失败不影响动作本身）
        if bus is not None:
            bus.publish_resolved({
                "requestId": result.get("requestId"),
                "decision": "confirmed",
                "level": result.get("action"),
                "requestedLevel": result.get("requestedLevel"),
                "gatePlan": plan,
                "stationName": cfg.server.station_name,
            })
    return result


@app.post("/api/brain/reject", dependencies=[Depends(require_token)])
def reject(req: RejectRequest) -> dict[str, Any]:
    """拒绝开闸。对应原型 ``GET /reject_open``。"""
    if brain is None:
        raise HTTPException(status_code=503, detail="大脑尚未初始化")

    result = brain.reject_open(req.reason, req.requestId)
    if result.get("accepted") and bridge is not None:
        # 拒绝 = 全部关闸
        close_plan = {"open": [], "close": brain.gates.open_gates()}
        bridge.apply_plan(close_plan)
        if close_plan["close"]:
            import time as _time
            brain.gates.commit(close_plan, now=_time.monotonic())
        if bus is not None:
            bus.publish_resolved({
                "requestId": result.get("requestId"),
                "decision": "rejected",
                "reason": req.reason,
                "stationName": cfg.server.station_name,
            })
    return result


@app.post("/api/brain/reset", dependencies=[Depends(require_token)])
def reset(req: ResetRequest | None = None) -> dict[str, Any]:
    """复位：清空历史窗口与闸门状态，回到预热期。

    默认保留冷却时间戳（设备保护不应被软件复位绕过）。
    """
    if brain is None:
        raise HTTPException(status_code=503, detail="大脑尚未初始化")

    clear = req.clearCooldowns if req else False
    close_plan = {"open": [], "close": brain.gates.open_gates()}
    brain.reset(clear_cooldowns=clear)
    if bridge is not None:
        bridge.apply_plan(close_plan)
    return {
        "accepted": True,
        "clearCooldowns": clear,
        "closedGates": close_plan["close"],
        "message": "状态已复位，将重新预热" + ("（冷却已清零）" if clear else "（冷却保持不变）"),
    }


@app.post("/api/brain/control", dependencies=[Depends(require_token)])
def manual_control(req: ControlRequest) -> dict[str, Any]:
    """人工直接控制闸门，绕过 AI 决策。

    给现场急停或应急处置用。三种用法：
    - ``{"state": 0}``：全部关闸（急停）
    - ``{"state": 1}``：按档位开 N 个门
    - ``{"relay": 3, "state": 0}``：单独关掉 3 号门（检修单路用）

    AI 侧状态同步复位，避免下一步又按旧历史决策。
    """
    if brain is None:
        raise HTTPException(status_code=503, detail="大脑尚未初始化")

    # 单路模式：直接动指定继电器
    if req.relay is not None:
        sent = bridge.set_relay(req.state, relay=req.relay) if bridge else False
        if sent:
            import time as _time
            brain.gates.commit(
                {"open": [req.relay] if req.state == 1 else [],
                 "close": [req.relay] if req.state == 0 else []},
                now=_time.monotonic(),
            )
        return {
            "accepted": True,
            "relay": req.relay,
            "requestedState": req.state,
            "dispatched": sent,
            "message": "单路指令已下发" if sent else "单路指令未下发（开关关闭或 MQTT 未连接）",
        }

    # 档位模式：0 = 全关，N = 开 N 个门
    import time as _time
    now = _time.monotonic()
    if req.state == 0:
        plan = {"open": [], "close": brain.gates.open_gates()}
        brain.gate.force_close()
    else:
        target = req.level if req.level is not None else req.state
        plan = brain.gates.plan(target, now=now)

    sent = bridge.apply_plan(plan) if bridge else 0
    if sent:
        brain.gates.commit(plan, now=now)

    return {
        "accepted": True,
        "requestedState": req.state,
        "targetLevel": req.level if req.level is not None else req.state,
        "plan": plan,
        "dispatchedCount": sent,
        "message": (
            f"已下发 {sent} 路指令" if sent
            else "指令未下发：可能因为控制开关关闭、MQTT 未连接，或状态未变化"
        ),
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=cfg.server.host,
        port=cfg.server.port,
        log_level="info",
    )
