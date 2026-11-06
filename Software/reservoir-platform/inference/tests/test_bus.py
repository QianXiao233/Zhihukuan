"""总线客户端的回归测试。

重点：**总线永远不能成为故障源**。
总线是"通知人去看"的旁路通道，开闸动作本身不依赖它。
所以每一个失败路径都必须安静降级，只记日志、绝不抛异常、
更不能阻塞 MQTT 的决策主循环。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bus_client import BusClient, BusConfig


class BusConfigTest(unittest.TestCase):

    def test_disabled_without_credentials(self):
        self.assertFalse(BusConfig().enabled)
        self.assertFalse(BusConfig(base_url="http://x").enabled)
        self.assertFalse(BusConfig(base_url="http://x", client_id="a").enabled)

    def test_enabled_only_with_all_three(self):
        cfg = BusConfig(base_url="http://x", client_id="a", client_secret="b")
        self.assertTrue(cfg.enabled)

    def test_defaults_match_backend_protocol(self):
        cfg = BusConfig()
        self.assertEqual(cfg.pending_topic, "brain.pending")
        self.assertEqual(cfg.approval_topic, "brain.approval")


class BusClientTest(unittest.TestCase):

    def test_publish_is_noop_when_disabled(self):
        """未配置时 publish 返回 False，但不抛异常。"""
        client = BusClient(BusConfig())
        self.assertFalse(client.publish_pending({"requestId": "x"}))
        self.assertFalse(client.publish_resolved({"requestId": "x"}))

    def test_unreachable_host_does_not_raise(self):
        """指向一个必定连不通的地址：必须安静失败。

        这是本类最重要的保证——总线挂了不能把决策循环带崩。
        """
        cfg = BusConfig(
            base_url="http://127.0.0.1:1",  # 1 端口几乎不可能有服务
            client_id="demo",
            client_secret="demo",
            timeout=1.0,
        )
        client = BusClient(cfg)
        self.assertFalse(client.publish_pending({"requestId": "x"}))
        self.assertIsNotNone(client.last_error)

    def test_stats_reflect_state(self):
        client = BusClient(BusConfig())
        stats = client.stats()
        self.assertFalse(stats["enabled"])
        self.assertEqual(stats["published"], 0)
        self.assertIsNone(stats["lastError"])


class ApprovalIdempotencyTest(unittest.TestCase):
    """requestId 的幂等语义：总线至少一次投递，重复/迟到的确认必须被拒。"""

    def make_gate(self):
        from brain.gate import ConfirmationConfig, GateController
        return GateController(ConfirmationConfig(reject_cooldown=30.0))

    def test_stale_request_id_rejected(self):
        gate = self.make_gate()
        gate.arbitrate(2, 1.3, "应急", "放水", 1.2, 5, gate_count=4)
        current = gate.pending.request_id
        self.assertTrue(current)

        # 用一个过期的 id 确认：必须被拒绝，且不能真的开闸
        result = gate.confirm(request_id="stale-id-123")
        self.assertFalse(result["accepted"])
        self.assertIn("currentRequestId", result)
        self.assertIsNotNone(gate.pending, "被拒的确认不应清掉待处理请求")

    def test_matching_request_id_accepted(self):
        gate = self.make_gate()
        gate.arbitrate(2, 1.3, "应急", "放水", 1.2, 5, gate_count=4)
        current = gate.pending.request_id

        result = gate.confirm(request_id=current)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["requestId"], current)

    def test_second_confirm_rejected(self):
        """同一条请求确认两次：第二次必须失败，避免重复开闸。"""
        gate = self.make_gate()
        gate.arbitrate(2, 1.3, "应急", "放水", 1.2, 5, gate_count=4)
        current = gate.pending.request_id

        self.assertTrue(gate.confirm(request_id=current)["accepted"])
        second = gate.confirm(request_id=current)
        self.assertFalse(second["accepted"], "重放的同一条确认必须被拒")

    def test_reject_with_stale_id_rejected(self):
        gate = self.make_gate()
        gate.arbitrate(2, 1.3, "应急", "放水", 1.2, 5, gate_count=4)
        result = gate.reject("reason", request_id="stale")
        self.assertFalse(result["accepted"])
        self.assertIsNotNone(gate.pending)

    def test_confirm_without_request_id_still_works(self):
        """不带 requestId 的确认（人工从界面直接点）应照常生效。"""
        gate = self.make_gate()
        gate.arbitrate(2, 1.3, "应急", "放水", 1.2, 5, gate_count=4)
        self.assertTrue(gate.confirm()["accepted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
