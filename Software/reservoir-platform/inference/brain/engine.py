"""决策引擎：把世界模型、MPC 规划、在线学习与闸门状态机组织成一次完整决策。

迁移并重组自智慧大坝 `dam_brain_enhanced_v2.py` 的主循环。
原版主循环同时承担「连 WebSocket、解析、决策、下发、打印」五件事；
这里只保留**决策内核**，数据接入与指令下发交给独立的客户端（见 ``mqtt_client.py``），
这样同一套决策逻辑既能跑在在线服务里，也能被离线回放/测试直接调用。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from brain.gate import ConfirmationConfig, GateController, GateState
from brain.gates import CoordinationConfig, GateArray
from brain.learner import LearningConfig, OnlineLearner
from brain.planner import CostWeights, Decision, MpcPlanner, PlanningConfig, WaterLevels
from brain.world_model import WaterScale, WorldModelRunner

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrainConfig:
    """引擎整体配置，集中在一处便于按现场调整。"""

    history_len: int | None = None
    """历史窗口；``None`` 表示以检查点里记录的长度为准。"""

    autosave_every: int = 500
    """每多少步把在线学习后的权重落盘一次；0 表示不落盘。"""

    autosave_dir: Path | None = None


class DamBrain:
    """决策内核。

    对外只有两个有意义的入口：

    * :meth:`observe` —— 喂入一帧水位，返回该执行的闸门动作与决策详情；
    * :meth:`status`  —— 导出可观测状态（供 ``/status`` 与前端面板使用）。

    内部维护：水位/动作历史窗口、经验回放、闸门状态机。
    """

    def __init__(
        self,
        checkpoint: Path,
        *,
        scale: WaterScale | None = None,
        levels: WaterLevels | None = None,
        weights: CostWeights | None = None,
        planning: PlanningConfig | None = None,
        learning: LearningConfig | None = None,
        confirmation: ConfirmationConfig | None = None,
        coordination: CoordinationConfig | None = None,
        config: BrainConfig | None = None,
    ) -> None:
        self.runner = WorldModelRunner(checkpoint, scale=scale)
        self.levels = levels or WaterLevels()
        self.config = config or BrainConfig()

        history_len = self.config.history_len or self.runner.history_len
        if history_len != self.runner.history_len:
            # 窗口长度与权重绑定的 LSTM 输入长度必须一致，否则推理结果无意义
            raise ValueError(
                f"history_len 配置({history_len}) 与检查点记录的长度({self.runner.history_len}) 不一致"
            )
        self.history_len = history_len

        self.planner = MpcPlanner(self.runner, levels=self.levels, weights=weights, config=planning)
        self.learner = OnlineLearner(self.runner, learning)
        self.gate = GateController(confirmation)
        self.gates = GateArray(coordination)

        # 动作历史里存的是**档位**（0..gate_count），不是单门 0/1。
        # 训练时模型见过的是 0/1，推理时用 predict_future_scaled 做线性缩放，
        # 所以 0 与 1 的含义保持一致，>1 的档位才需要缩放。
        self.water_history: deque[float] = deque(maxlen=self.history_len)
        self.action_history: deque[int] = deque(maxlen=self.history_len)

        self._lock = threading.RLock()
        self.step_count = 0
        self.last_prediction: float | None = None
        self.last_decision: Decision | None = None
        self.last_learn: dict[str, object] | None = None
        self.last_plan: dict[str, list[int]] | None = None
        self._last_tick = time.monotonic()
        self.started_at = None

    # ══════════════════════════════════════════════════════════
    # 主入口
    # ══════════════════════════════════════════════════════════

    def observe(self, water: float) -> dict[str, object] | None:
        """喂入一帧水位读数，返回本帧的仲裁结果。

        返回 ``None`` 表示该读数被丢弃（非法或历史窗口未满，处于预热期）。
        返回的字典包含：动作、决策详情、闸门状态、是否需要人工确认。
        """
        if not self.levels.is_valid(water):
            log.debug("丢弃非法水位读数: %r", water)
            return None

        with self._lock:
            # 累加闸门运行时长，供磨损均衡使用
            now = time.monotonic()
            self.gates.tick(now - self._last_tick)
            self._last_tick = now

            # 预热期：先攒满一个历史窗口，期间一律关闸
            if len(self.water_history) < self.history_len:
                self.water_history.append(water)
                self.action_history.append(0)
                self.gate.force_close()
                log.debug("预热中 %d/%d，水位 %.3f m", len(self.water_history), self.history_len, water)
                return None

            # 记录上一帧预测的误差，供在线学习统计
            if self.last_prediction is not None:
                self.learner.memory.add_error(self.last_prediction, water)

            # 把「上一帧真实执行的动作」和「上一帧的历史」组成一条经验
            if len(self.water_history) == self.history_len:
                self.learner.memory.add(list(self.water_history), list(self.action_history), water)

            # 更新窗口（先入队再做决策，保证决策用的是最新读数）
            prev_action = self.action_history[-1] if self.action_history else 0
            self.water_history.append(water)
            self.action_history.append(prev_action)
            self.step_count += 1

            hist_w = list(self.water_history)
            hist_a = list(self.action_history)
            capacity = self.gates.capacity

            # ── 1. AI 决策（档位 0..capacity）──
            decision = self.planner.decide(hist_w, hist_a, gate_count=capacity)
            self.last_decision = decision

            # ── 2. 安全仲裁（确认 + 冷却 + 保持）──
            hold = self.planner.hold_steps(hist_w)
            actual_level = self.gate.arbitrate(
                suggested_action=decision.action,
                water=decision.water,
                level=decision.level,
                explanation=decision.explanation,
                predicted_final=decision.predicted_final,
                hold_steps=hold,
                gate_count=capacity,
            )

            # ── 3. 档位 → 具体闸门组合（分档 + 轮换均衡）──
            plan = self.gates.plan(actual_level, now=now)
            self.last_plan = plan

            # 用实际执行的档位覆盖历史末位，让下一步的模型输入反映真实动作
            if self.action_history:
                self.action_history[-1] = actual_level

            # ── 4. 预测下一帧（供下一轮算误差）──
            self.last_prediction = self.runner.predict_next(
                list(self.water_history), list(self.action_history)
            )

            # ── 5. 按自适应间隔在线学习 ──
            if self.learner.should_learn(self.step_count):
                self.last_learn = self.learner.learn()
                self._maybe_autosave()

            return {
                "action": actual_level,
                "level": decision.level,
                "suggestedAction": decision.action,
                "decision": decision.to_dict(),
                "gate": self.gate.snapshot(),
                "gates": self.gates.snapshot(),
                "gatePlan": plan,
                "needsConfirmation": self.gate.state is GateState.PENDING,
                "step": self.step_count,
                "water": round(water, 4),
                "prediction": round(self.last_prediction, 4) if self.last_prediction is not None else None,
            }

    # ══════════════════════════════════════════════════════════
    # 人工裁决透传
    # ══════════════════════════════════════════════════════════

    def confirm_open(self, level: int | None = None, request_id: str | None = None) -> dict[str, object]:
        """确认开闸。``level`` 可由运维覆盖 AI 建议的档位。"""
        result = self.gate.confirm(level, request_id)
        if result.get("accepted"):
            # 确认后立即把档位落到具体闸门上，让调用方马上能下发
            self.last_plan = self.gates.plan(int(result["action"]), now=time.monotonic())
            result["gatePlan"] = self.last_plan
        return result

    def reject_open(self, reason: str = "", request_id: str | None = None) -> dict[str, object]:
        return self.gate.reject(reason, request_id)

    def reset(self, clear_cooldowns: bool = False) -> None:
        """复位历史与闸门状态（现场重新标定或长时间停机后使用）。

        参数 ``clear_cooldowns`` 默认 ``False``：冷却是对设备的保护，
        软件复位不应该把它一起抹掉。只有明确知道现场需要立刻重新决策时才置 ``True``。
        """
        with self._lock:
            self.water_history.clear()
            self.action_history.clear()
            self.step_count = 0
            self.last_prediction = None
            self.last_decision = None
            self.last_plan = None
            self.gate.force_close()
            # 闸门阵列也回到全关，但保留磨损统计——那是设备寿命数据，不该因为复位丢失
            self.gates.commit(
                {"open": self.gates.open_gates(), "close": self.gates.open_gates()},
                now=time.monotonic(),
            )
            if clear_cooldowns:
                self.gate.clear_cooldowns()

    # ══════════════════════════════════════════════════════════
    # 观测
    # ══════════════════════════════════════════════════════════

    def status(self) -> dict[str, object]:
        with self._lock:
            gw = list(self.water_history)
            return {
                "ready": len(gw) >= self.history_len,
                "step": self.step_count,
                "water": round(gw[-1], 4) if gw else None,
                "level": self.levels.level_name(gw[-1]) if gw else None,
                "rate": round(self.planner.rate(gw), 5) if gw else None,
                "prediction": round(self.last_prediction, 4) if self.last_prediction is not None else None,
                "gate": self.gate.snapshot(),
                "gates": self.gates.snapshot(),
                "gatePlan": self.last_plan,
                "decision": self.last_decision.to_dict() if self.last_decision else None,
                "learning": self.learner.stats(),
                "lastLearn": self.last_learn,
                "model": self.runner.describe(),
                "history": {
                    "length": len(gw),
                    "capacity": self.history_len,
                    "water": [round(w, 4) for w in gw],
                    "action": list(self.action_history),
                },
                "thresholds": {
                    "dead": self.levels.dead,
                    "critical": self.levels.critical,
                    "normalLow": self.levels.normal_low,
                    "normalHigh": self.levels.normal_high,
                    "warningHigh": self.levels.warning_high,
                    "emergency": self.levels.emergency,
                    "target": self.levels.target,
                },
            }

    # ══════════════════════════════════════════════════════════
    # 权重落盘
    # ══════════════════════════════════════════════════════════

    def _maybe_autosave(self) -> None:
        """在线学习会改变权重，定期落盘，避免进程重启丢失学习成果。"""
        if not self.config.autosave_every or not self.config.autosave_dir:
            return
        if self.learner.learn_count % self.config.autosave_every != 0:
            return
        try:
            self.config.autosave_dir.mkdir(parents=True, exist_ok=True)
            target = self.config.autosave_dir / f"world_model_online_{self.learner.learn_count}.pt"
            import torch

            torch.save(
                {
                    "model_state_dict": self.runner.model.state_dict(),
                    "water_mean": self.runner.water_mean,
                    "water_std": self.runner.water_std,
                    "history_len": self.runner.history_len,
                    "hidden_size": self.runner.hidden_size,
                    "num_layers": self.runner.num_layers,
                },
                target,
            )
            log.info("在线学习权重已保存: %s", target.name)
        except Exception as exc:  # 落盘失败不能影响主链路
            log.warning("权重落盘失败: %s", exc)
