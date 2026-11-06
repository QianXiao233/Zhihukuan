"""MPC 决策引擎：生成候选闸门动作序列，用世界模型推演并打分选优。

迁移自智慧大坝 `dam_brain_enhanced_v2.py` 的 ``deep_think`` / ``_generate_candidates`` /
``compute_cost`` / ``_calc_dynamic_hold_steps`` 等方法。

改动要点
--------
1. **阈值全部改成米制**，并与平台 ``dam_system_param`` 的语义对齐：
   死水位 / 濒死 / 正常 / 预警 / 应急 五档，不再是原始的 50/55/80/110/200。
2. **代价权重按米制重新标定**：原版的水位差项以「刻度单位」计（例如剧烈变化阈值
   是 3 个刻度），米制下对应 0.03 m，直接照搬会让惩罚几乎恒为 0 或爆表，
   因此这里单独定义 ``CostWeights`` 并给出量纲说明。
3. **保留原版的全部机理**：启发式候选、交替模式、最优解变异继承、动态保持帧数、
   加速度惩罚、超调惩罚。
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# 阈值配置（米）
# ══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class WaterLevels:
    """五档水位阈值（米）。默认值与平台 ``dam_system_param`` 的水位告警对齐。

    平台阈值表里水位是 0.20~1.20 m。这里把 0.20 作为「濒死」下限、
    1.20 作为「应急」上限，中间再划分正常与预警区间。
    """

    dead: float = 0.20
    critical: float = 0.30
    normal_low: float = 0.30
    normal_high: float = 0.80
    warning: float = 0.80
    warning_high: float = 1.10
    emergency: float = 1.20
    max_valid: float = 2.00

    # 目标水位：原版取「正常偏低」以免频繁开闸，这里取正常区间中位
    target: float = 0.60
    # 低于此值触发「加水」提示（原型里的 ADD_WATER_AT）
    add_water_at: float = 0.22

    def level_name(self, water: float) -> str:
        """把水位映射成中文等级标签，用于前端展示与日志。"""
        if water <= self.dead:
            return "死水位"
        if water <= self.critical:
            return "濒死"
        if water <= self.normal_high:
            return "正常"
        if water <= self.warning_high:
            return "预警"
        return "应急"

    def is_valid(self, water: float | None) -> bool:
        if water is None:
            return False
        return 0.0 <= water <= self.max_valid


@dataclass(frozen=True)
class CostWeights:
    """代价函数权重。

    每个权重都乘以一个「归一化比例」，所以数值可以按重要性直接比较：
    死水位 10000 远大于一切，保证安全优先；切换代价与浪费代价是小量，
    用于在同等安全的前提下鼓励少开闸、少换向。
    """

    dead: float = 10000.0
    critical: float = 500.0
    low: float = 100.0
    warning: float = 20.0
    emergency: float = 1000.0
    waste: float = 10.0
    switch: float = 5.0
    target_deviation: float = 2.0
    rapid_change: float = 8.0
    overshoot: float = 15.0
    acceleration: float = 10.0

    # 米制阈值：超过这个单帧变化量才算「剧烈」，对应原版 3 个刻度 = 0.03 m
    rapid_change_threshold: float = 0.03
    # 偏离目标超过该幅度才开始计罚，对应原版 10 个刻度 = 0.10 m
    target_tolerance: float = 0.10


@dataclass(frozen=True)
class PlanningConfig:
    horizon: int = 10
    random_candidates: int = 48
    mutate_candidates: int = 8
    # 应急水位直接开闸，不进搜索
    emergency_override: bool = True


# ══════════════════════════════════════════════════════════════
# 决策结果
# ══════════════════════════════════════════════════════════════

@dataclass
class Decision:
    """一次决策的完整产物，直接序列化给 Java 侧与前端。"""

    action: int
    """0=关闸, 1=开闸"""

    water: float
    """当前水位（米）"""

    level: str
    """水位等级中文名"""

    best_cost: float
    """最优候选的代价"""

    predicted_final: float
    """规划末端预测水位（米）"""

    rate: float
    """最近 5 帧的水位变化率（米/帧）"""

    explanation: str
    """面向人的决策解释"""

    candidate_count: int
    """本轮评估的候选序列数"""

    best_sequence: list[int] = field(default_factory=list)
    """最优动作序列，长度 = horizon。元素是**档位**（0..gate_count）"""

    forced: bool = False
    """是否由应急水位强制触发（未走搜索）"""

    gate_count: int = 1
    """规划时考虑的最大档位，即并联闸门数"""

    def to_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "water": round(self.water, 4),
            "level": self.level,
            "bestCost": round(self.best_cost, 3),
            "predictedFinal": round(self.predicted_final, 4),
            "rate": round(self.rate, 5),
            "explanation": self.explanation,
            "candidateCount": self.candidate_count,
            "bestSequence": self.best_sequence,
            "forced": self.forced,
            "gateCount": self.gate_count,
        }


class MpcPlanner:
    """基于世界模型的模型预测控制。

    用法：每次收到新水位时调用 :meth:`decide`，拿到动作与解释。
    规划器本身无状态（只有「上一步最优序列」用于变异继承），
    历史窗口由调用方（:class:`brain.engine.DamBrain`）维护。
    """

    def __init__(
        self,
        runner,
        levels: WaterLevels | None = None,
        weights: CostWeights | None = None,
        config: PlanningConfig | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.runner = runner
        self.levels = levels or WaterLevels()
        self.weights = weights or CostWeights()
        self.config = config or PlanningConfig()
        self._rng = rng or random.Random(20261106)

        self._last_best_seq: list[int] | None = None
        self.think_count = 0

    # ── 水位动态量 ────────────────────────────────────────────

    def rate(self, water_hist: list[float]) -> float:
        """最近 5 帧的平均水位变化率（米/帧）。"""
        if len(water_hist) >= 5:
            recent = water_hist[-5:]
            return (recent[-1] - recent[0]) / 5.0
        return 0.0

    def acceleration(self, water_hist: list[float]) -> float:
        """二阶变化：后 5 帧斜率减去前 5 帧斜率。"""
        if len(water_hist) >= 10:
            recent = water_hist[-10:]
            v1 = (recent[4] - recent[0]) / 5.0
            v2 = (recent[9] - recent[5]) / 5.0
            return v2 - v1
        return 0.0

    # ── 候选生成 ──────────────────────────────────────────────

    def generate_candidates(self, current_water: float, gate_count: int = 1) -> list[list[int]]:
        """组合式候选集：保底档位 + 启发式递增 + 交替 + 随机 + 上轮最优变异。

        ``gate_count`` 是并联闸门数，决定档位上限（0..gate_count）。
        所有候选序列的元素都在这个范围内。
        """
        h = self.config.horizon
        max_level = max(1, int(gate_count))

        candidates: list[list[int]] = [
            [0] * h,                 # 全关基线，
            [max_level] * h,         # 全开基线：极端情况下必须保证有可行解
        ]

        # 阶梯式候选：从 0 逐级升到 max_level，覆盖「渐进放水」
        for hold in range(1, max_level + 1):
            candidates.append([hold] * h)

        # 水位偏高：从不同时刻、不同档位开始放水
        if current_water >= self.levels.warning:
            for open_at in range(0, min(4, h)):
                for start_level in range(1, max_level + 1):
                    seq = [0] * h
                    for t in range(open_at, h):
                        seq[t] = start_level
                    candidates.append(seq)

        # 水位偏低：重复补全关，提高被选中的概率
        if current_water <= self.levels.critical + 0.05:
            candidates.append([0] * h)

        # 间歇放水：周期 2/3/4/5，模拟「少量多次」，档位取中间值
        mid_level = max(1, max_level // 2)
        for period in (2, 3, 4, 5):
            seq: list[int] = []
            on = True
            while len(seq) < h:
                for _ in range(period):
                    if len(seq) >= h:
                        break
                    seq.append(mid_level if on else 0)
                on = not on
            candidates.append(seq)

        # 随机探索：保持候选多样性，避免过早收敛到局部最优
        for _ in range(self.config.random_candidates):
            candidates.append([self._rng.randint(0, max_level) for _ in range(h)])

        # 上轮最优解变异：档位±1 做局部爬山
        if self._last_best_seq is not None:
            for _ in range(self.config.mutate_candidates):
                mutant = list(self._last_best_seq)
                n_mutate = self._rng.randint(1, 3)
                for p in self._rng.sample(range(h), min(n_mutate, h)):
                    # 在档位空间里做有界随机游走，而不是二值翻转
                    delta = 1 if self._rng.random() < 0.5 else -1
                    mutant[p] = max(0, min(max_level, mutant[p] + delta))
                candidates.append(mutant)

        return candidates

    # ── 代价评估 ──────────────────────────────────────────────

    def compute_cost(
        self,
        predicted: list[float],
        action_seq: list[int],
        rate: float,
        accel: float,
    ) -> float:
        """对一条预测轨迹打分，分越低越好。"""
        w = self.weights
        lv = self.levels
        total = 0.0

        for i, water in enumerate(predicted):
            # 安全区间惩罚（分段二次/线性，越危险增长越快）
            if water <= lv.dead:
                total += w.dead
            elif water <= lv.critical:
                span = max(lv.critical - lv.dead, 1e-6)
                ratio = (lv.critical - water) / span
                total += w.critical * ratio ** 2
            elif water < lv.normal_low:
                span = max(lv.normal_low - lv.critical, 1e-6)
                total += w.low * ((lv.normal_low - water) / span)
            elif water >= lv.emergency:
                # 米制下应急区间宽度取 0.30 m 作为归一化尺度
                total += w.emergency * ((water - lv.emergency) / 0.30) ** 2
            elif water >= lv.warning:
                span = max(lv.warning_high - lv.warning, 1e-6)
                ratio = (water - lv.warning) / span
                # 水位涨得越快，预警区间的惩罚越重
                if rate > 0.010:
                    total += w.warning * 2 * ratio
                elif rate > 0.003:
                    total += w.warning * ratio
                else:
                    total += w.warning * 0.5 * ratio

            # 偏离目标水位
            deviation = abs(water - lv.target)
            if deviation > w.target_tolerance:
                total += w.target_deviation * (deviation - w.target_tolerance) * 10

            # 超调：放水却降到目标以下，说明放多了。档位越高惩罚越重——
            # 4 个门全开的超调比 1 个门更严重
            if action_seq[i] > 0 and i > 0 and water < lv.target:
                total += w.overshoot * (lv.target - water) * 10 * action_seq[i]

            # 剧烈变化：保护闸门机械结构与下游
            if i > 0:
                change = abs(predicted[i] - predicted[i - 1])
                if change > w.rapid_change_threshold:
                    total += w.rapid_change * (change - w.rapid_change_threshold) * 100

        # 放水浪费：按「开着的门数 × 帧数」累计，开 4 个门是开 1 个门的 4 倍代价
        total += w.waste * sum(action_seq)

        # 档位切换：避免频繁增减闸门数。
        # 这里用「档位变化量的绝对值」而不是二元不同的次数——
        # 0→4 直接跳远比 0→1 伤害大，应该反映在代价里
        switches = sum(abs(action_seq[i] - action_seq[i - 1]) for i in range(1, len(action_seq)))
        total += w.switch * switches

        # 加速度：水位加速上涨更危险
        if accel > 0.002:
            total += accel * w.acceleration * 1000

        return total

    # ── 主决策入口 ────────────────────────────────────────────

    def decide(
        self,
        water_hist: list[float],
        action_hist: list[int],
        gate_count: int = 1,
    ) -> Decision:
        """跑一轮 MPC，返回最优档位与解释。

        ``gate_count`` 是当前可用闸门数，决定档位空间 0..gate_count。
        它是**运行时参数**而非构造参数：现场检修可能把某路门标为不可用，
        档位上限会随之缩小，不需要重建规划器。
        """
        current = water_hist[-1]
        level = self.levels.level_name(current)
        rate = self.rate(water_hist)
        accel = self.acceleration(water_hist)
        max_level = max(1, int(gate_count))

        # 应急水位：安全优先，直接全开，不做搜索。
        # 多门在这里尤其有意义——应急要的是最大排水能力
        if self.config.emergency_override and current >= self.levels.emergency:
            h = self.config.horizon
            seq = [max_level] * h
            return Decision(
                action=max_level, water=current, level=level, best_cost=0.0,
                predicted_final=current, rate=rate,
                explanation=(
                    f"应急水位 {current:.2f} m，安全第一，{max_level} 个闸门全开放水"
                ),
                candidate_count=0, best_sequence=seq, forced=True, gate_count=max_level,
            )

        self.think_count += 1
        candidates = self.generate_candidates(current, max_level)

        best_seq: list[int] | None = None
        best_cost = float("inf")
        best_pred: list[float] = []

        for seq in candidates:
            pred = self.runner.predict_future_scaled(
                water_hist, action_hist, seq, gate_count=max_level
            )
            cost = self.compute_cost(pred, seq, rate, accel)
            if cost < best_cost:
                best_cost, best_seq, best_pred = cost, seq, pred

        if best_seq is None:  # 理论上不可能，候选集永远非空
            best_seq = [0] * self.config.horizon
            best_pred = [current] * self.config.horizon
            best_cost = float("inf")

        self._last_best_seq = best_seq
        final_pred = best_pred[-1] if best_pred else current

        explanation = self.explain(current, level, best_seq[0], final_pred, rate, max_level)

        return Decision(
            action=best_seq[0],
            water=current,
            level=level,
            best_cost=best_cost,
            predicted_final=final_pred,
            rate=rate,
            explanation=explanation,
            candidate_count=len(candidates),
            best_sequence=best_seq,
            gate_count=max_level,
        )

    # ── 动态开闸保持 ──────────────────────────────────────────

    def hold_steps(self, water_hist: list[float], min_steps: int = 3, max_steps: int = 12) -> int:
        """根据水位变化趋势决定开闸后保持几帧。

        水位还在涨 → 多保持，确保真的把水放下去；降得快 → 少保持，避免放过头。
        """
        rate = self.rate(water_hist)
        if rate > 0.005:      # 米/帧，对应原版 0.5 刻度
            return max_steps
        if rate > -0.003:     # 对应原版 -0.3
            return min(min_steps + 2, max_steps)
        if rate < -0.010:     # 对应原版 -1.0
            return min_steps
        return min(min_steps + 2, max_steps)

    # ── 人话解释 ──────────────────────────────────────────────

    def explain(
        self,
        water: float,
        level: str,
        action: int,
        prediction: float,
        rate: float,
        gate_count: int = 1,
    ) -> str:
        """把决策翻译成一句运维人员能直接读懂的理由。

        ``action`` 是档位（0..gate_count），文案里会明确说「开 N 个门」，
        而不是笼统的「开闸」——运维需要知道到底动了几路。
        """
        if rate > 0.010:
            trend = "水位快速上涨"
        elif rate > 0.003:
            trend = "水位缓慢上涨"
        elif rate < -0.010:
            trend = "水位快速下降"
        elif rate < -0.003:
            trend = "水位缓慢下降"
        else:
            trend = "水位基本稳定"

        lv = self.levels
        total = max(1, int(gate_count))

        if action > 0:
            gate_text = f"开启 {action} 个闸门（共 {total} 个）"
            if water >= lv.emergency:
                return f"应急水位 {water:.2f} m，必须立即{gate_text}全力放水"
            if water >= lv.warning:
                return f"水位 {water:.2f} m 且{trend}，{gate_text}主动放水，避免继续升高"
            return f"水位 {water:.2f} m 且{trend}，{gate_text}预防性放水以维持健康水位"

        if water <= lv.critical:
            return f"已接近死水位 {water:.2f} m，必须全部关闸蓄水，不能再放"
        if water <= lv.target:
            return f"水位偏低 {water:.2f} m，全部关闸蓄水，防止跌入濒死区间"
        if rate < -0.005:
            return f"水位正在自然下降（{rate:+.4f} m/帧），关闸等待即可，不必浪费水"
        if abs(rate) < 0.003:
            return f"水位 {water:.2f} m 稳定在安全范围，关闸省水"
        if prediction <= lv.normal_high:
            return f"预测水位将自然回落到安全区间（{prediction:.2f} m），关闸等待即可"
        return f"水位 {water:.2f} m 处于安全范围，综合省水与设备保护，关闸最优"
