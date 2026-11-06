"""多闸门协调的回归测试。

覆盖三块核心逻辑：

1. **分档**：需要 N 档就必须恰好开 N 个门，不能多也不能少；
2. **磨损均衡**：长期运行后各门累计时长应大致接近；
3. **最小切换**：档位微调时尽量少动已开的门。

以及多档位下的世界模型推演和代价函数行为。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.gates import CoordinationConfig, GateArray
from brain.planner import CostWeights, MpcPlanner, PlanningConfig, WaterLevels

CHECKPOINT = Path(__file__).resolve().parent.parent / "models" / "world_model.pt"


class GateArrayPlanTest(unittest.TestCase):
    """档位 → 具体闸门的映射。"""

    def make(self, count=4, **kw) -> GateArray:
        return GateArray(CoordinationConfig(gate_count=count, min_hold_seconds=0, **kw))

    def test_zero_level_opens_nothing(self):
        ga = self.make()
        self.assertEqual(ga.plan(0, now=0.0), {"open": [], "close": []})

    def test_level_n_opens_exactly_n(self):
        for n in range(0, 5):
            ga = self.make()
            plan = ga.plan(n, now=0.0)
            self.assertEqual(len(plan["open"]), n, f"档位 {n} 应开 {n} 个门")

    def test_level_clamped_to_capacity(self):
        ga = self.make(count=4)
        plan = ga.plan(99, now=0.0)
        self.assertEqual(len(plan["open"]), 4, "超过容量应截断到 4")

    def test_expanding_keeps_existing_gates(self):
        """档位从 2 扩到 4 时，已开的 2 个应保留，只补开 2 个。"""
        ga = self.make()
        ga.commit(ga.plan(2, now=0.0), now=0.0)
        opened = set(ga.open_gates())
        self.assertEqual(len(opened), 2)

        plan = ga.plan(4, now=10.0)
        self.assertEqual(plan["close"], [], "扩张时不应关门")
        self.assertEqual(len(plan["open"]), 2, "应补开 2 个")
        self.assertFalse(opened & set(plan["open"]), "补开的不能是已经开着的")

    def test_shrinking_closes_only_needed(self):
        """档位从 4 降到 2 时，只关 2 个，且保留已开的。"""
        ga = self.make()
        ga.commit(ga.plan(4, now=0.0), now=0.0)
        plan = ga.plan(2, now=10.0)
        self.assertEqual(len(plan["close"]), 2)
        self.assertEqual(plan["open"], [])
        self.assertEqual(ga.current_level(), 4, "plan 不应改变状态，需 commit 才生效")

        ga.commit(plan, now=10.0)
        self.assertEqual(ga.current_level(), 2)

    def test_no_change_returns_empty_plan(self):
        """档位没变时应返回空方案，避免无谓的 MQTT 流量。"""
        ga = self.make()
        ga.commit(ga.plan(2, now=0.0), now=0.0)
        plan = ga.plan(2, now=10.0)
        self.assertEqual(plan["open"], [])
        self.assertEqual(plan["close"], [])


class GateArrayWearBalanceTest(unittest.TestCase):
    """磨损均衡：长期运行后各门累计时长应接近。"""

    def test_shortest_runtime_preferred(self):
        ga = GateArray(CoordinationConfig(gate_count=4, min_hold_seconds=0))

        # 先让 1、2 号门跑很久
        ga.commit(ga.plan(2, now=0.0), now=0.0)
        self.assertEqual(sorted(ga.open_gates()), [1, 2])
        ga.tick(1000.0)

        # 全部关闭后再开 2 门：应该优先选运行时长最短的 3、4 号
        ga.commit(ga.plan(0, now=10.0), now=10.0)
        plan = ga.plan(2, now=20.0)
        self.assertEqual(sorted(plan["open"]), [3, 4],
                         "应优先选累计运行时长最短的闸门")

    def test_usage_accumulates_only_when_open(self):
        ga = GateArray(CoordinationConfig(gate_count=2, min_hold_seconds=0))
        ga.commit(ga.plan(1, now=0.0), now=0.0)
        ga.tick(60.0)

        snapshot = ga.snapshot()
        on_gates = [g for g in snapshot["gates"] if g["state"] == 1]
        off_gates = [g for g in snapshot["gates"] if g["state"] == 0]
        self.assertEqual(len(on_gates), 1)
        self.assertAlmostEqual(on_gates[0]["onSeconds"], 60.0, places=1)
        self.assertAlmostEqual(off_gates[0]["onSeconds"], 0.0, places=1)

    def test_alternating_opens_balances_over_time(self):
        """反复 0→2→0 循环若干次后，四个门的累计时长应大致均衡。"""
        ga = GateArray(CoordinationConfig(gate_count=4, min_hold_seconds=0))
        now = 0.0
        for _ in range(20):
            plan = ga.plan(2, now=now)
            ga.commit(plan, now=now)
            now += 10
            ga.tick(10.0)          # 开 10 秒
            plan = ga.plan(0, now=now)
            ga.commit(plan, now=now)
            now += 1

        times = [g["onSeconds"] for g in ga.snapshot()["gates"]]
        spread = max(times) - min(times)
        # 完美均衡时每个门应 ~100 秒；允许一定偏差，但不应出现某门完全没跑过
        self.assertGreater(min(times), 0, f"不应有闸门从未运行: {times}")
        self.assertLess(spread, max(times) * 0.8,
                        f"磨损过于不均: {times}")


class GateArrayAvailabilityTest(unittest.TestCase):
    """故障隔离：不可用的门不参与协调。"""

    def test_unavailable_gate_excluded(self):
        ga = GateArray(CoordinationConfig(gate_count=4, min_hold_seconds=0))
        ga.set_available(2, False)
        self.assertEqual(ga.capacity, 3, "可用容量应降为 3")

        plan = ga.plan(3, now=0.0)
        self.assertEqual(len(plan["open"]), 3)
        self.assertNotIn(2, plan["open"], "不可用的门不能被打开")

    def test_all_unavailable_yields_zero_capacity(self):
        ga = GateArray(CoordinationConfig(gate_count=2, min_hold_seconds=0))
        ga.set_available(1, False)
        ga.set_available(2, False)
        self.assertEqual(ga.capacity, 0)
        self.assertEqual(ga.plan(3, now=0.0), {"open": [], "close": []})

    def test_invalid_gate_id_raises(self):
        ga = GateArray(CoordinationConfig(gate_count=4))
        with self.assertRaises(ValueError):
            ga.set_available(5, False)


class GateArraySyncTest(unittest.TestCase):
    """用固件上报校正内部状态。"""

    def test_sync_adopts_firmware_truth(self):
        ga = GateArray(CoordinationConfig(gate_count=4, min_hold_seconds=0))
        ga.commit(ga.plan(2, now=0.0), now=0.0)
        self.assertEqual(len(ga.open_gates()), 2)

        # 固件上报：实际只有 3 号开着（说明指令没执行成功或被人手动改了）
        ga.sync_from_report([0, 0, 1, 0, 0, 0, 0, 0])
        self.assertEqual(ga.open_gates(), [3], "应以固件上报为准")

    def test_sync_ignores_extra_relays(self):
        """固件上报 8 路，但本系统只用前 4 路。"""
        ga = GateArray(CoordinationConfig(gate_count=4, min_hold_seconds=0))
        ga.sync_from_report([1, 0, 0, 0, 1, 1, 1, 1])
        self.assertEqual(ga.open_gates(), [1], "第 5~8 路不参与本系统")


class CostWithLevelsTest(unittest.TestCase):
    """多档位下的代价函数。"""

    def setUp(self):
        self.planner = MpcPlanner(
            None, levels=WaterLevels(), weights=CostWeights(),
            config=PlanningConfig(horizon=4),
        )

    def cost(self, preds, actions):
        return self.planner.compute_cost(preds, actions, 0.0, 0.0)

    def test_more_gates_costs_more_waste(self):
        """同等水位下，开 4 个门的浪费代价应高于开 1 个门。"""
        one = self.cost([0.6] * 4, [1, 1, 1, 1])
        four = self.cost([0.6] * 4, [4, 4, 4, 4])
        self.assertGreater(four, one)

    def test_big_jump_costs_more_than_small_jump(self):
        """0→4 的档位跳变应比 0→1 代价更高。"""
        small = self.cost([0.6] * 4, [1, 0, 0, 0])
        big = self.cost([0.6] * 4, [4, 0, 0, 0])
        # 注意 wasted 也随档位增加，这里主要验证方向正确
        self.assertGreater(big, small)


class CandidateLevelTest(unittest.TestCase):
    """候选序列的档位范围。"""

    def test_candidates_within_level_range(self):
        planner = MpcPlanner(None, config=PlanningConfig(horizon=6, random_candidates=20))
        for gate_count in (1, 2, 4):
            candidates = planner.generate_candidates(0.9, gate_count)
            for seq in candidates:
                for level in seq:
                    self.assertGreaterEqual(level, 0)
                    self.assertLessEqual(level, gate_count,
                                         f"档位 {level} 超出上限 {gate_count}")

    def test_full_open_baseline_uses_max_level(self):
        planner = MpcPlanner(None, config=PlanningConfig(horizon=5, random_candidates=0))
        candidates = planner.generate_candidates(0.6, gate_count=4)
        self.assertIn([0] * 5, candidates)
        self.assertIn([4] * 5, candidates, "全开基线应为最大档位")

    def test_each_level_has_steady_candidate(self):
        """0..N 每个档位都应有一个恒定候选，便于快速评估固定档位。"""
        planner = MpcPlanner(None, config=PlanningConfig(horizon=4, random_candidates=0))
        candidates = planner.generate_candidates(0.6, gate_count=4)
        for level in range(0, 5):
            self.assertIn([level] * 4, candidates, f"缺少档位 {level} 的恒定候选")


@unittest.skipUnless(CHECKPOINT.exists(), f"缺少模型检查点: {CHECKPOINT}")
class MultiGateIntegrationTest(unittest.TestCase):
    """真实模型 + 四闸门的端到端行为。"""

    def make(self, count=4):
        from brain import CoordinationConfig as CC
        from brain.engine import DamBrain
        return DamBrain(CHECKPOINT, coordination=CC(gate_count=count))

    def test_capacity_reflects_gate_count(self):
        for n in (1, 2, 4):
            brain = self.make(n)
            self.assertEqual(brain.gates.capacity, n)

    def test_emergency_opens_all_gates(self):
        brain = self.make(4)
        for w in (1.22, 1.24, 1.26, 1.28, 1.30, 1.32, 1.34, 1.36, 1.38, 1.40):
            brain.observe(w)
        result = brain.observe(1.45)
        self.assertEqual(result["suggestedAction"], 4, "应急应建议全开")
        self.assertTrue(result["decision"]["forced"])

        confirmed = brain.confirm_open()
        self.assertEqual(confirmed["action"], 4)
        brain.gates.commit(confirmed["gatePlan"], now=0.0)
        self.assertEqual(sorted(brain.gates.open_gates()), [1, 2, 3, 4])

    def test_operator_can_lower_level(self):
        """运维可以把 AI 建议的档位调低。"""
        brain = self.make(4)
        for w in (1.22, 1.24, 1.26, 1.28, 1.30, 1.32, 1.34, 1.36, 1.38, 1.40):
            brain.observe(w)
        result = brain.observe(1.45)
        self.assertEqual(result["suggestedAction"], 4)

        confirmed = brain.confirm_open(level=1)
        self.assertEqual(confirmed["action"], 1, "应按运维指定降到 1 门")
        self.assertEqual(confirmed["requestedLevel"], 4, "但要记录 AI 原本的建议")

    def test_normal_water_keeps_gates_closed(self):
        brain = self.make(4)
        for _ in range(12):
            brain.observe(0.62)
        result = brain.observe(0.62)
        self.assertEqual(result["suggestedAction"], 0)
        self.assertEqual(result["gatePlan"], {"open": [], "close": []})

    def test_plan_only_contain_needed_changes(self):
        """稳态下不应反复产生开关指令。"""
        brain = self.make(4)
        for _ in range(12):
            brain.observe(0.55)
        result = brain.observe(0.55)
        plan = result["gatePlan"]
        self.assertEqual(plan["open"], [])
        self.assertEqual(plan["close"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
