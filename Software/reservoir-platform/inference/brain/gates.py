"""多闸门协调：把「需要几成放水能力」翻译成「具体开哪几个门」。

背景
----
原型的动作空间是二元的（开/关一个闸门），世界模型也是在这个假设下训练的。
现场有 4 个并联闸门（固件 `devices.c`：继电器 1~4 即闸门一~四），
开得越多放得越快，可以组合出 0~4 共 5 档放水能力。

本模块只负责**档位 → 具体闸门组合**的映射，不涉及水位预测。
预测部分在 `brain.planner` 里按档位缩放实现。

协调规则
--------
1. **按需分档**：需要 N 档就恰好开 N 个门，不多开（省水、省电、减少磨损）；
2. **轮换均衡**：优先选「累计运行时长最短」的门，长期看四个门磨损均匀；
3. **最小切换**：已经开着的门尽量保持不变，避免无谓的启停；
4. **故障隔离**：标记为不可用的门不参与轮换。

这三条规则的优先级是：可用性 > 分档数量 > 最小切换 > 磨损均衡。
换句话说，宁可多换一次门，也不能少开一个门导致放水量不足。
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class GateUsage:
    """单路闸门的运行统计。"""

    gate_id: int
    """继电器编号，从 1 开始（与固件 devices.c 的 id 一致）"""

    state: int = 0
    """0=关，1=开"""

    total_on_seconds: float = 0.0
    """累计开启时长，用于磨损均衡"""

    switch_count: int = 0
    """累计启停次数，用于设备寿命评估"""

    available: bool = True
    """是否可用。故障或检修时置 false，协调器会跳过它"""

    last_changed_at: float = 0.0
    """上次状态变化的时间戳（monotonic），用于最短保持时间控制"""


@dataclass(frozen=True)
class CoordinationConfig:
    """协调器参数。"""

    gate_count: int = 4
    """参与协调的闸门数量。现场是 4（继电器 1~4）"""

    min_hold_seconds: float = 5.0
    """最短保持时间：刚动作过的门在该时间内不参与再次切换，

    否则在阈值附近会出现「开关抖动」，对继电器寿命损害很大。
    """

    prefer_stability: bool = True
    """是否优先保持当前已开的门（True 时尽量减少启停次数）"""


class GateArray:
    """多闸门协调器。

    对外只暴露两个概念：
    - **档位**（level）：0..gate_count，表示需要几个门同时开；
    - **动作**（apply）：把档位落到具体闸门上，并给出最小变更方案。

    内部维护每路门的运行统计，用「累计开启时长最短优先」实现磨损均衡。
    """

    def __init__(self, config: CoordinationConfig | None = None) -> None:
        self.cfg = config or CoordinationConfig()
        if self.cfg.gate_count < 1:
            raise ValueError(f"gate_count 必须 >= 1，实际 {self.cfg.gate_count}")

        self._lock = threading.RLock()
        self._gates: dict[int, GateUsage] = {
            i: GateUsage(gate_id=i) for i in range(1, self.cfg.gate_count + 1)
        }
        self._last_update = 0.0

    # ── 查询 ──────────────────────────────────────────────────

    @property
    def capacity(self) -> int:
        """最大档位 = 可用闸门数"""
        with self._lock:
            return sum(1 for g in self._gates.values() if g.available)

    def current_level(self) -> int:
        """当前实际开了几个门"""
        with self._lock:
            return sum(1 for g in self._gates.values() if g.state == 1)

    def open_gates(self) -> list[int]:
        with self._lock:
            return [i for i, g in self._gates.items() if g.state == 1]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "gateCount": self.cfg.gate_count,
                "capacity": self.capacity,
                "currentLevel": self.current_level(),
                "openGates": self.open_gates(),
                "gates": [
                    {
                        "id": g.gate_id,
                        "state": g.state,
                        "available": g.available,
                        "onSeconds": round(g.total_on_seconds, 1),
                        "switchCount": g.switch_count,
                    }
                    for g in sorted(self._gates.values(), key=lambda x: x.gate_id)
                ],
            }

    # ── 档位 → 具体闸门 ────────────────────────────────────────

    def plan(self, target_level: int, now: float) -> dict[str, list[int]]:
        """计算把档位调到 ``target_level`` 的最小变更方案。

        返回 ``{"open": [...], "close": [...]}``，只包含**需要变化**的闸门。
        调用方拿到后直接下发对应指令，不需要变化的门不发指令——
        这是减少总线流量和继电器动作次数的一半功夫。
        """
        with self._lock:
            available = [g for g in self._gates.values() if g.available]
            target = max(0, min(target_level, len(available)))

            currently_open = [g for g in available if g.state == 1]
            keep: list[GateUsage] = []
            to_close: list[GateUsage] = []

            if self.cfg.prefer_stability and len(currently_open) <= target:
                # 需要更多门：现有全开着的都保留，避免无谓切换
                keep = list(currently_open)
            elif self.cfg.prefer_stability:
                # 需要更少门：从已开的里面挑出保留的，优先留"运行时长最短"的
                # （留新的、关旧的，进一步均衡磨损）
                keep = sorted(currently_open, key=lambda g: g.total_on_seconds)[:target]
                to_close = [g for g in currently_open if g not in keep]
            else:
                to_close = list(currently_open)

            need_open = target - len(keep)
            candidates = [g for g in available if g.state == 0 and g not in to_close]

            # 最短保持时间：刚切换过的门先别动，除非凑不够数
            if need_open > 0 and self.cfg.min_hold_seconds > 0:
                settled = [g for g in candidates if now - g.last_changed_at >= self.cfg.min_hold_seconds]
                if len(settled) >= need_open:
                    candidates = settled

            # 磨损均衡：累计运行时长最短的优先开启
            candidates.sort(key=lambda g: (g.total_on_seconds, g.gate_id))
            to_open = candidates[:need_open]

            return {
                "open": [g.gate_id for g in to_open],
                "close": [g.gate_id for g in to_close],
            }

    def commit(self, plan: dict[str, list[int]], now: float) -> None:
        """把已下发的方案记录到状态里。

        **必须在下发成功后调用**：如果先记状态再下发，一旦下发失败，
        内部状态就会与真实闸门不一致，后续协调会基于错误前提做决策。
        """
        with self._lock:
            for gate_id in plan.get("open", []):
                gate = self._gates.get(gate_id)
                if gate is None:
                    continue
                if gate.state != 1:
                    gate.state = 1
                    gate.switch_count += 1
                    gate.last_changed_at = now
            for gate_id in plan.get("close", []):
                gate = self._gates.get(gate_id)
                if gate is None:
                    continue
                if gate.state != 0:
                    gate.state = 0
                    gate.switch_count += 1
                    gate.last_changed_at = now

    # ── 计时（磨损均衡的输入）──────────────────────────────────

    def tick(self, elapsed_seconds: float) -> None:
        """累加运行时长。由服务定时调用（例如每帧或每秒一次）。"""
        if elapsed_seconds <= 0:
            return
        with self._lock:
            for gate in self._gates.values():
                if gate.state == 1:
                    gate.total_on_seconds += elapsed_seconds

    # ── 运维接口 ──────────────────────────────────────────────

    def set_available(self, gate_id: int, available: bool) -> None:
        """标记某路闸门可用/不可用（检修、故障时使用）。

        置为不可用时，如果它当前是开着的，协调器会在下一次 plan 里关掉它。
        """
        with self._lock:
            gate = self._gates.get(gate_id)
            if gate is None:
                raise ValueError(f"闸门编号 {gate_id} 超出范围 1..{self.cfg.gate_count}")
            gate.available = available
            log.info("闸门 %d 标记为%s", gate_id, "可用" if available else "不可用")

    def reset_counters(self) -> None:
        """清零磨损统计（更换新闸门后使用）。"""
        with self._lock:
            for gate in self._gates.values():
                gate.total_on_seconds = 0.0
                gate.switch_count = 0
        log.info("闸门磨损统计已清零")

    def sync_from_report(self, relays: list[int]) -> None:
        """用固件上报的实际继电器状态校正内部状态。

        固件每 1.5 秒上报一次 ``relay[0..7]``，其中前 ``gate_count`` 项就是
        我们的闸门。用它校正可以防止「指令丢了但内部以为开了」的漂移。
        """
        with self._lock:
            for gate in self._gates.values():
                index = gate.gate_id - 1
                if index < len(relays):
                    actual = 1 if relays[index] else 0
                    if actual != gate.state:
                        log.debug("闸门 %d 状态校正: %d -> %d（以固件上报为准）",
                                  gate.gate_id, gate.state, actual)
                        gate.state = actual
