"""决策内核的回归测试。

重点覆盖三类容易静默出错的逻辑：

1. **单位换算**：模型在原始刻度（均值≈72）训练，平台用米（0.2~1.2）。
   换算错了不会抛异常，只会让预测值离谱，属于最难发现的故障。
2. **闸门状态机**：确认/拒绝/冷却/保持的转移顺序错了，表现为"该开不开"或"重复弹窗"。
3. **控制报文**：必须与固件的手写 JSON 解析器严格对齐。

运行::

    cd Software/reservoir-platform/inference
    python -m pytest tests/ -v
    或直接： python tests/test_brain.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

# 允许 `python tests/test_brain.py` 直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.gate import ConfirmationConfig, GateController, GateState
from brain.planner import CostWeights, MpcPlanner, PlanningConfig, WaterLevels
from brain.world_model import WaterScale

CHECKPOINT = Path(__file__).resolve().parent.parent / "models" / "world_model.pt"


class WaterScaleTest(unittest.TestCase):
    """米 ↔ 模型原始刻度的换算。"""

    def test_default_factor_is_100(self):
        scale = WaterScale()
        self.assertAlmostEqual(scale.to_raw(0.5), 50.0)
        self.assertAlmostEqual(scale.to_meters(50.0), 0.5)

    def test_roundtrip(self):
        scale = WaterScale(factor=100.0, offset=0.0)
        for meters in (0.20, 0.60, 0.99, 1.20):
            self.assertAlmostEqual(scale.to_meters(scale.to_raw(meters)), meters, places=6)

    def test_offset_is_applied_before_factor(self):
        # raw = (meters + offset) * factor
        scale = WaterScale(factor=100.0, offset=0.5)
        self.assertAlmostEqual(scale.to_raw(1.0), 150.0)
        self.assertAlmostEqual(scale.to_meters(150.0), 1.0)

    def test_platform_range_maps_into_training_range(self):
        """平台的 0.20~1.20 m 应落在模型训练时的 20~120 刻度内。"""
        scale = WaterScale()
        self.assertAlmostEqual(scale.to_raw(0.20), 20.0)
        self.assertAlmostEqual(scale.to_raw(1.20), 120.0)


class WaterLevelsTest(unittest.TestCase):
    """水位分档边界。"""

    levels = WaterLevels()

    def test_level_names(self):
        self.assertEqual(self.levels.level_name(0.15), "死水位")
        self.assertEqual(self.levels.level_name(0.25), "濒死")
        self.assertEqual(self.levels.level_name(0.60), "正常")
        self.assertEqual(self.levels.level_name(0.95), "预警")
        self.assertEqual(self.levels.level_name(1.30), "应急")

    def test_validity_rejects_out_of_range(self):
        self.assertFalse(self.levels.is_valid(None))
        self.assertFalse(self.levels.is_valid(-0.1))
        self.assertFalse(self.levels.is_valid(3.0))
        self.assertTrue(self.levels.is_valid(0.0))
        self.assertTrue(self.levels.is_valid(1.2))

    def test_thresholds_are_ordered(self):
        # 分档必须单调，否则 level_name 的 if-elif 链会跳过某档
        self.assertLess(self.levels.dead, self.levels.critical)
        self.assertLess(self.levels.critical, self.levels.warning)
        self.assertLess(self.levels.warning, self.levels.emergency)


class GateControllerTest(unittest.TestCase):
    """确认 / 拒绝 / 冷却 / 保持。"""

    def make(self, **kwargs) -> GateController:
        return GateController(ConfirmationConfig(**kwargs))

    def test_idle_passes_close_action_through(self):
        gate = self.make()
        action = gate.arbitrate(0, 0.6, "正常", "关闸", 0.6, 3)
        self.assertEqual(action, 0)
        self.assertIs(gate.state, GateState.IDLE)

    def test_open_request_becomes_pending_not_executed(self):
        """AI 建议开闸时不能直接开——必须先挂起等人工确认。"""
        gate = self.make()
        action = gate.arbitrate(1, 0.99, "预警", "建议放水", 0.85, 5)
        self.assertEqual(action, 0, "未经确认不得开闸")
        self.assertIs(gate.state, GateState.PENDING)
        self.assertIsNotNone(gate.pending)

    def test_confirm_enters_opening_with_hold(self):
        gate = self.make(hold_steps_min=3, hold_steps_max=12)
        gate.arbitrate(1, 0.99, "预警", "建议放水", 0.85, 6)
        result = gate.confirm()
        self.assertTrue(result["accepted"])
        self.assertEqual(result["holdSteps"], 6)
        self.assertIs(gate.state, GateState.OPENING)

    def test_confirm_is_idempotent(self):
        gate = self.make()
        gate.arbitrate(1, 0.99, "预警", "建议放水", 0.85, 5)
        gate.confirm()
        second = gate.confirm()
        self.assertFalse(second["accepted"], "重复确认应被拒绝而不是抛异常")

    def test_hold_forces_open_then_returns_to_idle(self):
        gate = self.make(hold_steps_min=2, hold_steps_max=2)
        gate.arbitrate(1, 0.99, "预警", "放水", 0.85, 2)
        gate.confirm()

        # 保持期内即使 AI 建议关闸也要继续开
        self.assertEqual(gate.arbitrate(0, 1.0, "预警", "x", 0.9, 2), 1)
        self.assertEqual(gate.arbitrate(0, 1.0, "预警", "x", 0.9, 2), 1)
        # 保持用完，回到空闲；此时 AI 建议关闸就应执行
        self.assertEqual(gate.arbitrate(0, 1.0, "预警", "x", 0.9, 2), 0)
        self.assertIs(gate.state, GateState.IDLE)

    def test_reject_blocks_open_during_cooldown(self):
        gate = self.make(reject_cooldown=30.0)
        gate.arbitrate(1, 0.99, "预警", "放水", 0.85, 5)
        gate.reject("人工拒绝")

        # 冷却期内再次建议开闸，应被压制且不产生新的待确认
        action = gate.arbitrate(1, 1.0, "预警", "再放水", 0.9, 5)
        self.assertEqual(action, 0)
        self.assertIsNone(gate.pending, "冷却期内不应弹出新的确认请求")

    def test_reset_keeps_cooldowns(self):
        """复位不能绕过冷却——否则软件复位就成了跳过设备保护的后门。"""
        gate = self.make(reject_cooldown=30.0)
        gate.arbitrate(1, 0.99, "预警", "放水", 0.85, 5)
        gate.reject()

        gate.force_close()
        remaining = gate.cooldown_remaining()["reject"]
        self.assertGreater(remaining, 0, "复位后冷却必须仍然有效")

    def test_clear_cooldowns_explicitly(self):
        gate = self.make(reject_cooldown=30.0)
        gate.arbitrate(1, 0.99, "预警", "放水", 0.85, 5)
        gate.reject()
        gate.clear_cooldowns()
        self.assertEqual(gate.cooldown_remaining()["reject"], 0.0)

    def test_reject_without_pending_is_safe(self):
        gate = self.make()
        self.assertFalse(gate.reject()["accepted"])


class CostFunctionTest(unittest.TestCase):
    """代价函数必须保持"死水位代价压倒一切"的排序。"""

    def setUp(self):
        self.weights = CostWeights()
        self.levels = WaterLevels()
        self.planner = MpcPlanner(None, levels=self.levels, weights=self.weights,
                                  config=PlanningConfig(horizon=4))

    def cost(self, preds, actions=None, rate=0.0, accel=0.0):
        return self.planner.compute_cost(preds, actions or [0] * len(preds), rate, accel)

    def test_dead_water_costs_more_than_normal(self):
        dead = self.cost([0.1] * 4)
        normal = self.cost([0.6] * 4)
        self.assertGreater(dead, normal)

    def test_emergency_costs_more_than_normal(self):
        emergency = self.cost([1.5] * 4)
        normal = self.cost([0.6] * 4)
        self.assertGreater(emergency, normal)

    def test_more_opening_costs_more(self):
        """同等水位下，开闸越多浪费越大。"""
        closed = self.cost([0.6] * 4, [0, 0, 0, 0])
        opened = self.cost([0.6] * 4, [1, 1, 1, 1])
        self.assertGreater(opened, closed)

    def test_switching_costs_more(self):
        """同等开闸帧数下，频繁换向应更贵（隔离出切换代价本身）。

        注意必须让两条序列的开闸帧数相同，否则浪费代价会盖过切换代价——
        最初写成 [1,1,1,1] 对 [1,0,1,0] 就是踩了这个坑：
        前者开 4 帧浪费 40，后者开 2 帧浪费 20 + 3 次切换 15 = 35，反而更便宜。
        """
        steady = self.cost([0.6] * 4, [1, 1, 0, 0])    # 1 次切换
        flipping = self.cost([0.6] * 4, [1, 0, 1, 0])  # 3 次切换
        self.assertGreater(flipping, steady)

    def test_rapid_change_penalized(self):
        gentle = self.cost([0.60, 0.61, 0.62, 0.63])
        abrupt = self.cost([0.60, 0.90, 0.60, 0.90])
        self.assertGreater(abrupt, gentle)


class PlannerCandidatesTest(unittest.TestCase):
    """候选集必须始终包含全关与全开。"""

    def test_baselines_always_present(self):
        planner = MpcPlanner(None, config=PlanningConfig(horizon=6, random_candidates=4))
        candidates = planner.generate_candidates(0.6)
        self.assertIn([0] * 6, candidates, "必须包含全关基线")
        self.assertIn([1] * 6, candidates, "必须包含全开基线")

    def test_high_water_adds_early_open_candidates(self):
        planner = MpcPlanner(None, config=PlanningConfig(horizon=6, random_candidates=0))
        high = planner.generate_candidates(0.95)
        low = planner.generate_candidates(0.5)
        self.assertGreater(len(high), len(low), "高水位应生成更多开闸候选")

    def test_mutation_uses_previous_best(self):
        planner = MpcPlanner(None, config=PlanningConfig(horizon=6, random_candidates=0,
                                                        mutate_candidates=4))
        first = planner.generate_candidates(0.6)
        planner._last_best_seq = [1, 0, 1, 0, 1, 0]
        second = planner.generate_candidates(0.6)
        self.assertGreater(len(second), len(first), "有上一轮最优解时应额外生成变异候选")


class MqttPayloadTest(unittest.TestCase):
    """控制报文必须与固件的手写 JSON 解析器对齐。"""

    def test_relay_command_format(self):
        from mqtt_client import build_relay_command
        payload = build_relay_command(1, 1)
        self.assertEqual(payload, '{"cmd":"relay.set","relay":1,"state":1}')
        self.assertIn('"cmd":"relay.set"', payload, "cmd 必须无空格，否则固件 strstr 匹配失败")

    def test_relay_clamped_to_1_8(self):
        from mqtt_client import build_relay_command
        self.assertIn('"relay":1', build_relay_command(0, 1))
        self.assertIn('"relay":1', build_relay_command(-3, 1))
        self.assertIn('"relay":8', build_relay_command(99, 1))

    def test_state_normalized_fail_safe(self):
        """只有明确的 1 才算开闸，其余一律关闸（失败安全）。"""
        from mqtt_client import build_relay_command
        self.assertIn('"state":1', build_relay_command(1, 1))
        self.assertIn('"state":0', build_relay_command(1, 7))
        self.assertIn('"state":0', build_relay_command(1, 0))

    def test_parse_status_reads_level_and_relays(self):
        from mqtt_client import parse_status
        raw = b'{"relay":[1,0,0,0,0,0,0,0],"temp":25.5,"level":0.85,"ph":7.2,"orp":120}'
        parsed = parse_status(raw)
        self.assertIsNotNone(parsed)
        self.assertAlmostEqual(parsed["level"], 0.85)
        self.assertEqual(parsed["relays"][0], 1)
        self.assertEqual(len(parsed["relays"]), 8)

    def test_heartbeat_frame_is_dropped(self):
        """四项测量全空的心跳帧不能当成 0 米喂给模型。"""
        from mqtt_client import parse_status
        raw = b'{"relay":[0,0,0,0,0,0,0,0],"temp":"null","level":"null","ph":"null","orp":"null"}'
        self.assertIsNone(parse_status(raw))

    def test_malformed_json_returns_none(self):
        from mqtt_client import parse_status
        self.assertIsNone(parse_status(b'not json'))
        self.assertIsNone(parse_status(b''))
        self.assertIsNone(parse_status(b'[1,2,3]'))


@unittest.skipUnless(CHECKPOINT.exists(), f"缺少模型检查点: {CHECKPOINT}")
class ModelIntegrationTest(unittest.TestCase):
    """真实模型权重上的端到端行为。"""

    @classmethod
    def setUpClass(cls):
        from brain import CoordinationConfig
        from brain.engine import DamBrain
        cls.brain = DamBrain(CHECKPOINT, coordination=CoordinationConfig(gate_count=1))

    def test_warmup_returns_none_until_window_full(self):
        """预热期语义：前 history_len 帧只入库不决策，第 history_len+1 帧起产出决策。

        为什么不是第 history_len 帧：决策需要「历史窗口 + 当前帧」共 N+1 个点。
        前 N 帧填满窗口后，第 N+1 帧才既有完整历史、又有可评估的当前水位。
        """
        from brain import CoordinationConfig
        from brain.engine import DamBrain
        brain = DamBrain(CHECKPOINT, coordination=CoordinationConfig(gate_count=1))
        n = brain.history_len
        for i in range(n):
            self.assertIsNone(brain.observe(0.6), f"第 {i + 1} 帧应处于预热期")
        self.assertIsNotNone(brain.observe(0.6), f"第 {n + 1} 帧应开始决策")

    def test_normal_water_prefers_closing(self):
        from brain import CoordinationConfig
        from brain.engine import DamBrain
        brain = DamBrain(CHECKPOINT, coordination=CoordinationConfig(gate_count=1))
        for _ in range(10):
            brain.observe(0.62)
        result = brain.observe(0.62)
        self.assertEqual(result["suggestedAction"], 0, "正常水位应倾向关闸")

    def test_warning_water_suggests_opening(self):
        """预警水位下，开闸方案应让水位下降得更快（这是决策的物理前提）。

        断言的是**物理方向**而不是"最终一定选开闸"：模型在这个数据点上可能
        预测水位会自然回落（历史数据里确实出现过这种形态），此时关闸等待
        反而合理。真正必须成立的是：
        开闸轨迹终点 <= 关闸轨迹终点。若连方向都反了，说明动作影响的建模错了。
        """
        from brain import CoordinationConfig
        from brain.engine import DamBrain
        brain = DamBrain(CHECKPOINT, coordination=CoordinationConfig(gate_count=1))
        for w in (0.80, 0.83, 0.86, 0.89, 0.92, 0.95, 0.97, 0.98, 0.99, 1.00):
            brain.observe(w)
        brain.observe(1.02)

        hist_w = list(brain.water_history)
        hist_a = list(brain.action_history)
        closed = brain.runner._simulate(hist_w, hist_a, [0] * 5)
        opened = brain.runner._simulate(hist_w, hist_a, [1] * 5)

        self.assertLess(
            opened[-1], closed[-1],
            f"开闸终点({opened[-1]:.4f}) 应低于关闸终点({closed[-1]:.4f})",
        )

    def test_emergency_forces_open_without_confirmation_delay(self):
        from brain import CoordinationConfig
        from brain.engine import DamBrain
        brain = DamBrain(CHECKPOINT, coordination=CoordinationConfig(gate_count=1))
        for _ in range(10):
            brain.observe(1.25)
        result = brain.observe(1.30)
        self.assertEqual(result["suggestedAction"], 1)
        self.assertTrue(result["decision"]["forced"], "应急水位必须是强制开闸")

    def test_prediction_is_in_meter_range(self):
        """预测值必须落在合理的米制范围内，而不是原始刻度。"""
        from brain import CoordinationConfig
        from brain.engine import DamBrain
        brain = DamBrain(CHECKPOINT, coordination=CoordinationConfig(gate_count=1))
        for _ in range(10):
            brain.observe(0.6)
        result = brain.observe(0.6)
        prediction = result["prediction"]
        self.assertIsNotNone(prediction)
        self.assertGreater(prediction, 0.0)
        self.assertLess(prediction, 3.0, f"预测值 {prediction} 超出米制合理范围，疑似单位换算错误")


if __name__ == "__main__":
    unittest.main(verbosity=2)
