"""LSTM 世界模型：从历史水位与闸门动作预测下一时刻水位。

迁移自智慧大坝 `dam_brain_enhanced_v2.py` 的同名类，保持网络结构与权重完全兼容，
使原来的 `.pt` 检查点无需重新训练即可加载。

与原始版本的关键差异
--------------------
原版直接以「原始刻度」（实测区间约 50~140）训练与推理；本项目的平台水位以
**米**为单位，阈值是 0.20~1.20。如果直接把米制读数喂进模型，归一化后会落到
训练分布之外，预测必然失真。因此这里引入 :class:`WaterScale`，
在模型边界统一做「平台单位 → 原始刻度」的双向换算，模型内部逻辑一行未改。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import torch
import torch.nn as nn

log = logging.getLogger(__name__)


class WorldModel(nn.Module):
    """单步水位预测网络。

    输入是「水位历史 + 动作历史」两条等长序列，输出下一时刻的水位（归一化空间）。
    结构必须与保存的检查点严格一致，否则 `load_state_dict` 会失败。
    """

    def __init__(self, history_len: int = 10, hidden_size: int = 64, num_layers: int = 2) -> None:
        super().__init__()
        self.history_len = history_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.lstm = nn.LSTM(
            input_size=2,  # [水位, 动作]
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
        )
        self.output_head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1),
        )

    def forward(self, water_seq: torch.Tensor, action_seq: torch.Tensor) -> torch.Tensor:
        x = torch.stack([water_seq, action_seq.float()], dim=-1)
        lstm_out, _ = self.lstm(x)
        return self.output_head(lstm_out[:, -1, :])

    def predict_sequence(
        self,
        water_hist: torch.Tensor,
        action_hist: torch.Tensor,
        future_actions: list[int],
        steps: int,
    ) -> list[float]:
        """自回归推演：把每一步的预测值回填进历史窗口，模拟未来 ``steps`` 帧。

        注意原始实现用 Python list 逐帧滚动，这里保持同样的滚动语义，
        只是把张量设备统一交给调用方管理，避免每帧重复搬移。
        """
        self.eval()
        device = next(self.parameters()).device
        cur_w = water_hist[0].tolist()
        cur_a = action_hist[0].tolist()
        preds: list[float] = []
        with torch.no_grad():
            for i in range(steps):
                w = torch.tensor([cur_w], dtype=torch.float32, device=device)
                a = torch.tensor([cur_a], dtype=torch.float32, device=device)
                nw = self.forward(w, a).item()
                preds.append(nw)
                cur_w = cur_w[1:] + [nw]
                cur_a = cur_a[1:] + [float(future_actions[i])]
        return preds


@dataclass(frozen=True)
class WaterScale:
    """平台单位（米）与模型训练刻度之间的换算。

    模型在原始装置的刻度上训练，其归一化参数 ``mean``/``std`` 也是那个刻度的。
    这里用一对线性系数完成换算：

        raw = (meters + offset) * factor

    默认 ``factor=100``、``offset=0``，即「米 × 100」——这是根据训练数据
    （均值 72.2、范围约 50~140）与平台阈值（0.20~1.20 m 对应 20~120）
    对照得出的一致换算。若现场换了量程，只改配置即可，不必重新训练。
    """

    factor: float = 100.0
    offset: float = 0.0

    def to_raw(self, meters: float) -> float:
        return (meters + self.offset) * self.factor

    def to_meters(self, raw: float) -> float:
        return raw / self.factor - self.offset


class WorldModelRunner:
    """检查点加载器 + 单位适配后的推理门面。

    对外只暴露「米」制接口，内部负责换算，使服务层与平台其余部分的单位一致。
    """

    def __init__(self, checkpoint: Path, scale: WaterScale | None = None) -> None:
        if not checkpoint.exists():
            raise FileNotFoundError(f"世界模型检查点不存在: {checkpoint}")

        # weights_only=False 是必需的：检查点里除了张量还存了 water_mean 等标量元数据
        ckpt = torch.load(checkpoint, map_location="cpu", weights_only=False)
        self.history_len: int = int(ckpt["history_len"])
        self.hidden_size: int = int(ckpt["hidden_size"])
        self.num_layers: int = int(ckpt["num_layers"])
        self.water_mean: float = float(ckpt["water_mean"])
        self.water_std: float = float(ckpt["water_std"])
        if self.water_std < 1e-6:
            raise ValueError(f"检查点中的 water_std 异常（{self.water_std}），模型无法正常归一化")

        self.model = WorldModel(self.history_len, self.hidden_size, self.num_layers)
        self.model.load_state_dict(ckpt["model_state_dict"])
        self.model.eval()

        self.scale = scale or WaterScale()
        self.checkpoint = checkpoint

        log.info(
            "世界模型已加载: %s | 历史窗口=%d 隐藏层=%d 层数=%d | 归一化均值=%.2f 标准差=%.2f",
            checkpoint.name, self.history_len, self.hidden_size, self.num_layers,
            self.water_mean, self.water_std,
        )

    # ── 单位换算 ──────────────────────────────────────────────

    def _raw_to_norm(self, raw: float) -> float:
        return (raw - self.water_mean) / self.water_std

    # ── 推理接口（全部使用「米」）───────────────────────────────

    def predict_next(self, water_hist_m: list[float], action_hist: list[int]) -> float | None:
        """预测下一帧水位（米）。历史不足一个窗口时返回 ``None``。"""
        if len(water_hist_m) < self.history_len:
            return None

        raw = [self.scale.to_raw(w) for w in water_hist_m[-self.history_len:]]
        norm = [self._raw_to_norm(v) for v in raw]

        w = torch.tensor([norm], dtype=torch.float32)
        a = torch.tensor([action_hist[-self.history_len:]], dtype=torch.float32)
        with torch.no_grad():
            pred_norm = self.model(w, a).item()

        raw_pred = pred_norm * self.water_std + self.water_mean
        return self.scale.to_meters(raw_pred)

    def predict_future(
        self,
        water_hist_m: list[float],
        action_hist: list[int],
        action_seq: list[int],
    ) -> list[float]:
        """给定未来动作序列，推演每一步的水位（米）。

        ``action_seq`` 的元素是**档位**（0=全关，N=开 N 个门），
        不是单门的 0/1。多门叠加通过 :meth:`predict_future_scaled` 处理。
        """
        return self.predict_future_scaled(water_hist_m, action_hist, action_seq, gate_count=1)

    def predict_future_scaled(
        self,
        water_hist_m: list[float],
        action_hist: list[int],
        action_seq: list[int],
        gate_count: int,
    ) -> list[float]:
        """多闸门并联时的水位推演。

        建模依据与局限
        --------------
        世界模型是在「单门开/关」上训练的，动作输入只有 0 和 1。现在最多 4 个门
        同时开，不能直接把 0~4 喂进去——那是训练分布之外的输入，输出无意义。

        这里采用**单门基准 + 线性叠加**的近似：

        1. 先用模型算出「单门完全开」和「单门全关」两个基准轨迹；
        2. 每个时刻的净变化量 = 开闸轨迹 - 关闸轨迹；
        3. 实际 N 个门时，把净变化量按 N 倍缩放，叠加到「全关基准」上。

        即 ``water(N) ≈ base_closed + N * (base_open - base_closed)``。

        **这个近似的成立条件**：多个门放的是同一水体、出水口互不干扰、
        且总流量未超出模型训练时见过的量级。超出 4 门全开时误差会放大——
        因为水位下降速率不可能随门数无限线性增长，最终受来水量限制。

        为控制误差，代码里对倍率做了上限截断（``max_scale``），
        宁可低估放水能力，也不给出过于乐观的预测导致决策激进。
        """
        if not action_seq:
            return []

        gate_count = max(1, int(gate_count))

        # 单门全关 / 单门全开两条基准轨迹
        closed_seq = [0] * len(action_seq)
        open_seq = [1] * len(action_seq)

        base_closed = self._simulate(water_hist_m, action_hist, closed_seq)
        base_open = self._simulate(water_hist_m, action_hist, open_seq)

        results: list[float] = []
        # 线性外推的倍率上限：4 门时允许到 4 倍，但再多就不再放大，
        # 因为模型的单门流量本身已经是在特定水位差下测得的
        max_scale = float(gate_count)

        for step, level in enumerate(action_seq):
            if level <= 0:
                # 全关：直接用关闸基准，避免缩放引入误差
                results.append(base_closed[step])
                continue
            delta = base_open[step] - base_closed[step]
            scale = min(float(level), max_scale)
            results.append(base_closed[step] + delta * scale)

        return results

    def _simulate(
        self,
        water_hist_m: list[float],
        action_hist: list[int],
        action_seq: list[int],
    ) -> list[float]:
        """内部：按给定的单门 0/1 序列做自回归推演。"""
        raw = [self.scale.to_raw(w) for w in water_hist_m[-self.history_len:]]
        norm = [self._raw_to_norm(v) for v in raw]

        water_t = torch.tensor([norm], dtype=torch.float32)
        action_t = torch.tensor([action_hist[-self.history_len:]], dtype=torch.float32)
        preds_norm = self.model.predict_sequence(water_t, action_t, action_seq, len(action_seq))

        return [self.scale.to_meters(p * self.water_std + self.water_mean) for p in preds_norm]

    # ── 在线学习支持 ──────────────────────────────────────────

    def normalize_batch(self, water_batch: torch.Tensor) -> torch.Tensor:
        """把「米」为单位的批量水位换算到模型归一化空间（供在线学习使用）。"""
        raw = (water_batch + self.scale.offset) * self.scale.factor
        return (raw - self.water_mean) / self.water_std

    def predict_batch(self, water_norm: torch.Tensor, action_batch: torch.Tensor) -> torch.Tensor:
        return self.model(water_norm, action_batch)

    def describe(self) -> dict[str, object]:
        return {
            "checkpoint": self.checkpoint.name,
            "history_len": self.history_len,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "water_mean": round(self.water_mean, 3),
            "water_std": round(self.water_std, 3),
            "scale_factor": self.scale.factor,
            "scale_offset": self.scale.offset,
        }
