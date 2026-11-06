"""开闸确认与冷却状态机。

迁移自智慧大坝 `dam_brain_enhanced_v2.py` 的 ``pending_open`` / ``confirm_flag`` /
``confirm_lock`` / ``REJECT_COOLDOWN`` / ``OPEN_COOLDOWN`` / ``gate_just_opened`` 一组散落状态。

为什么要重写而不是照搬
----------------------
原版把这些状态直接摊在 ``DamBrain`` 的实例属性上，靠主循环里嵌套的 ``if`` 推进，
共有 8 个布尔/时间戳字段互相牵扯。在单线程 ``async for`` 循环里能跑通，
但放到 FastAPI 这种多线程环境，两个请求同时进来就可能出现
「确认了但冷却期没刷新」「重复弹窗」等问题。

这里把它们收敛成一个显式的有限状态机，状态转移集中在一处，并对所有操作加锁。
状态图：

    IDLE ──决策为开闸且通过冷却──▶ PENDING ──确认──▶ OPENING（保持 N 帧）──▶ IDLE
      ▲                              │
      └──────────拒绝（进冷却）───────┘
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum

log = logging.getLogger(__name__)


class GateState(str, Enum):
    IDLE = "idle"
    """空闲：闸门处于已知的关闭/稳定状态，可以接受新的开闸请求。"""

    PENDING = "pending"
    """已建议开闸，等待人工确认。此时闸门动作不变。"""

    OPENING = "opening"
    """已确认，闸门正在开启并保持若干个决策帧。"""


@dataclass
class ConfirmationConfig:
    """冷却与保持参数（秒 / 帧）。

    默认值沿用原版：拒绝与开闸各 30 秒冷却，保持 3~12 帧。
    """

    reject_cooldown: float = 30.0
    open_cooldown: float = 30.0
    hold_steps_min: int = 3
    hold_steps_max: int = 12
    # 待确认请求的存活时间：超时无人处理则自动失效，避免陈旧弹窗
    pending_ttl: float = 120.0


@dataclass
class PendingRequest:
    """一次待确认的开闸建议。"""

    water: float
    level: str
    explanation: str
    predicted_final: float
    requested_level: int = 1
    """AI 建议开启的闸门数（1..gate_count）"""

    request_id: str = ""
    """本次请求的稳定标识。用于总线的 at-least-once 投递去重，
    以及把"确认动作"与总线上那条事件对应起来。"""

    created_at: float = field(default_factory=time.monotonic)

    def age(self) -> float:
        return time.monotonic() - self.created_at

    def to_dict(self) -> dict[str, object]:
        return {
            "requestId": self.request_id,
            "water": round(self.water, 4),
            "level": self.level,
            "explanation": self.explanation,
            "predictedFinal": round(self.predicted_final, 4),
            "requestedLevel": self.requested_level,
            "ageSeconds": round(self.age(), 1),
        }


class GateController:
    """闸门动作的确认与冷却仲裁器。

    调用方（:class:`brain.engine.DamBrain`）每帧把 AI 建议交给 :meth:`arbitrate`，
    得到一个「本轮实际应执行的档位」。所有安全约束都在这里统一收口。
    """

    def __init__(self, cfg: ConfirmationConfig | None = None) -> None:
        self.cfg = cfg or ConfirmationConfig()
        self._lock = threading.RLock()

        self._state = GateState.IDLE
        self._pending: PendingRequest | None = None
        self._last_open_at: float = 0.0
        self._last_reject_at: float = 0.0

        self._hold_remaining: int = 0
        self._hold_level: int = 1
        """保持期内应维持的档位"""

        self._planned_hold: int = 0
        """确认时使用的保持帧数"""

        self.current_action: int = 0
        """当前实际档位（0 = 全关）"""

    # ── 只读视图 ──────────────────────────────────────────────

    @property
    def state(self) -> GateState:
        with self._lock:
            # 待确认请求过期后自动回到空闲
            if self._state is GateState.PENDING and self._pending is not None:
                if self._pending.age() > self.cfg.pending_ttl:
                    log.info("待确认的开闸建议已超时（%.0fs），自动失效", self._pending.age())
                    self._state = GateState.IDLE
                    self._pending = None
            return self._state

    @property
    def pending(self) -> PendingRequest | None:
        with self._lock:
            return self._pending

    def cooldown_remaining(self) -> dict[str, float]:
        """返回两类冷却的剩余秒数，供前端显示倒计时。"""
        with self._lock:
            now = time.monotonic()
            return {
                "reject": max(0.0, self.cfg.reject_cooldown - (now - self._last_reject_at))
                if self._last_reject_at else 0.0,
                "open": max(0.0, self.cfg.open_cooldown - (now - self._last_open_at))
                if self._last_open_at else 0.0,
            }

    # ── 核心仲裁 ──────────────────────────────────────────────

    def arbitrate(
        self,
        suggested_action: int,
        water: float,
        level: str,
        explanation: str,
        predicted_final: float,
        hold_steps: int,
        gate_count: int = 1,
    ) -> int:
        """把 AI 的建议档位与安全约束合成为这一帧真正执行的档位。

        参数 ``suggested_action`` 是**档位**（0..gate_count），不再是 0/1。
        返回同样是对外应执行的档位。

        返回 0 但状态是 PENDING 时，表示「建议已记录、正在等人工确认」。
        """
        max_level = max(1, int(gate_count))

        with self._lock:
            now = time.monotonic()

            # 1. 保持期内强制执行已确认的档位，直到帧数用完
            if self._state is GateState.OPENING:
                if self._hold_remaining > 0:
                    self._hold_remaining -= 1
                    self.current_action = self._hold_level
                    return self._hold_level
                log.info("开闸保持结束，恢复自主决策")
                self._state = GateState.IDLE
                self.current_action = 0
                # 继续往下走，本帧按新建议评估

            # 2. 正在等确认：期间保持全关
            if self._state is GateState.PENDING:
                return 0

            # 3. AI 建议全关：直接执行，不需要确认
            if suggested_action <= 0:
                self.current_action = 0
                return 0

            # 4. AI 建议开闸：逐项检查冷却
            if self._last_reject_at and (now - self._last_reject_at) < self.cfg.reject_cooldown:
                remaining = int(self.cfg.reject_cooldown - (now - self._last_reject_at))
                log.debug("拒绝冷却中，剩余 %ds，压制开闸", remaining)
                return 0

            if self._last_open_at and (now - self._last_open_at) < self.cfg.open_cooldown:
                remaining = int(self.cfg.open_cooldown - (now - self._last_open_at))
                log.debug("开闸冷却中，剩余 %ds，压制开闸", remaining)
                return 0

            # 5. 通过全部检查：挂起为待确认，等待人工放行
            self._state = GateState.PENDING
            import uuid
            self._pending = PendingRequest(
                water=water,
                level=level,
                explanation=explanation,
                predicted_final=predicted_final,
                requested_level=max(1, min(int(suggested_action), max_level)),
                request_id=uuid.uuid4().hex[:16],
            )
            # 记住本次计划保持的帧数与档位，确认时使用
            self._planned_hold = max(self.cfg.hold_steps_min, min(hold_steps, self.cfg.hold_steps_max))
            self._hold_level = self._pending.requested_level
            log.info(
                "AI 建议开闸 %d 个门（水位 %.2f m，%s），等待人工确认",
                self._pending.requested_level, water, level,
            )
            return 0

    # ── 人工裁决 ──────────────────────────────────────────────

    def confirm(self, level: int | None = None, request_id: str | None = None) -> dict[str, object]:
        """人工确认开闸。

        ``level`` 允许运维在确认时**调整档位**（比如 AI 建议开 3 个门，
        但现场判断只开 1 个就够）。省略时按 AI 建议的档位执行。

        ``request_id`` 用于幂等：总线是 at-least-once，同一条待确认请求可能
        被投递多次。带着旧 requestId 的迟到确认会被拒绝，避免"已经处理过的
        请求被重放，导致闸门在无人知情的情况下再开一次"——这在物理控制里是
        必须防的事故类型。

        幂等：没有待确认请求时返回 ``accepted=False`` 而不是抛异常，
        避免前端重复点击导致 500。
        """
        with self._lock:
            if self._state is not GateState.PENDING or self._pending is None:
                return {"accepted": False, "reason": "当前没有待确认的开闸请求"}

            # 迟到/重放的确认：requestId 不匹配当前待处理请求
            if request_id and self._pending.request_id and request_id != self._pending.request_id:
                log.warning(
                    "忽略过期的开闸确认（请求 %s，当前待处理 %s）",
                    request_id, self._pending.request_id,
                )
                return {
                    "accepted": False,
                    "reason": "该请求已失效或被更新的请求替代",
                    "currentRequestId": self._pending.request_id,
                }

            hold = getattr(self, "_planned_hold", self.cfg.hold_steps_min)
            requested = self._pending.requested_level
            # 运维指定档位时以运维为准，但仍受上限约束
            final_level = requested if level is None else max(1, min(int(level), requested))

            self._state = GateState.OPENING
            self._hold_remaining = hold
            self._hold_level = final_level
            self._last_open_at = time.monotonic()
            self.current_action = final_level
            water = self._pending.water
            resolved_id = self._pending.request_id
            self._pending = None

            log.info("开闸已确认，开 %d 个门，保持 %d 帧", final_level, hold)
            return {
                "accepted": True,
                "holdSteps": hold,
                "action": final_level,
                "requestedLevel": requested,
                "requestId": resolved_id,
                "water": round(water, 4),
                "message": f"已确认，开启 {final_level} 个闸门",
            }

    def reject(self, reason: str = "", request_id: str | None = None) -> dict[str, object]:
        """人工拒绝开闸，进入拒绝冷却期。``request_id`` 语义同 :meth:`confirm`。"""
        with self._lock:
            if self._state is not GateState.PENDING:
                return {"accepted": False, "reason": "当前没有待确认的开闸请求"}

            if request_id and self._pending and self._pending.request_id \
                    and request_id != self._pending.request_id:
                return {
                    "accepted": False,
                    "reason": "该请求已失效或被更新的请求替代",
                    "currentRequestId": self._pending.request_id,
                }

            resolved_id = self._pending.request_id if self._pending else ""
            self._state = GateState.IDLE
            self._pending = None
            self._last_reject_at = time.monotonic()
            self.current_action = 0

            log.info("开闸被拒绝，进入 %.0f 秒冷却%s", self.cfg.reject_cooldown,
                     f"（{reason}）" if reason else "")
            return {
                "accepted": True,
                "requestId": resolved_id,
                "cooldownSeconds": int(self.cfg.reject_cooldown),
                "message": f"已拒绝，{int(self.cfg.reject_cooldown)} 秒内不再建议开闸",
            }

    def force_close(self) -> None:
        """强制复位到空闲并关闸（用于人工急停或服务重启后的状态对齐）。

        **不清除冷却时间戳**。冷却是对设备的安全约束，不应因为一次软件复位就消失——
        否则「复位 → 立刻再开闸」会绕过 30 秒保护。需要清除时请显式调用
        :meth:`clear_cooldowns`。
        """
        with self._lock:
            self._state = GateState.IDLE
            self._pending = None
            self._hold_remaining = 0
            self.current_action = 0
            log.info("闸门状态已复位为关闸空闲（冷却时间保持不变）")

    def clear_cooldowns(self) -> None:
        """清除拒绝/开闸冷却。仅用于现场调试或长时间停机后的重新开始。"""
        with self._lock:
            self._last_reject_at = 0.0
            self._last_open_at = 0.0
            log.info("冷却已清零")

    # ── 状态导出 ──────────────────────────────────────────────

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "state": self.state.value,
                "pending": self._pending.to_dict() if self._pending else None,
                "currentAction": self.current_action,
                "holdRemaining": self._hold_remaining,
                "cooldown": {k: round(v, 1) for k, v in self.cooldown_remaining().items()},
            }
