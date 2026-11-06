"""在线学习：经验回放 + 难例挖掘 + 误差趋势驱动的自适应学习频率。

迁移自智慧大坝 `dam_brain_enhanced_v2.py` 的 ``ExperienceMemory`` 与 ``online_learn``。

设计取舍
--------
原版在同一个进程里边推理边训练，本服务沿用这一模式，但做了三点工程化加固：

1. **训练与推理串行化**：用一把锁把 ``train_step`` 与预测隔开。原版单线程循环里
   天然不会并发，但这里服务是多线程（HTTP 请求可能并发进来），不加锁会出现
   「一边 forward 一边 optimizer.step」的读后写竞争。
2. **只在 eval 模式下推理**：训练前后显式切换 ``train()``/``eval()``，
   避免 Dropout（本例没有）与 BatchNorm（本例没有）状态残留——保持与原版一致。
3. **线程安全的内存快照**：``sample_batch`` 取出的是数据副本，
   训练过程即使耗时较长也不会阻塞新样本入队。
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from dataclasses import dataclass

import numpy as np
import torch
import torch.nn as nn

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LearningConfig:
    """在线学习超参。

    默认值沿用原版，只把「固定间隔」改成「自适应区间」的两个端点。
    """

    memory_size: int = 500
    batch_size: int = 64
    epochs: int = 5
    lr: float = 1e-4

    # 自适应学习间隔（步）：误差大就缩小间隔，误差小就放大
    learn_interval_min: int = 15
    learn_interval_max: int = 100
    learn_interval_step: int = 10
    learn_interval_default: int = 50

    # 误差阈值（米）。原版是 5.0 / 1.5 个刻度，米制下除以 100
    error_high: float = 0.05
    error_low: float = 0.015
    # 误差趋势（米/批）
    trend_high: float = 0.01
    trend_low: float = -0.005

    # 最近样本加权倍数（难例挖掘的简化实现）
    recent_boost: float = 1.5
    recent_window: int = 50


class ExperienceMemory:
    """经验回放池。

    存的是三元组 ``(水位历史, 动作历史, 下一帧水位)``，外加一份最近的预测误差序列，
    误差既用于展示，也用于驱动学习频率自适应。
    """

    def __init__(self, capacity: int = 500) -> None:
        self._water: deque[list[float]] = deque(maxlen=capacity)
        self._action: deque[list[int]] = deque(maxlen=capacity)
        self._next: deque[float] = deque(maxlen=capacity)
        self._errors: deque[float] = deque(maxlen=100)
        self._trend: deque[float] = deque(maxlen=20)
        self._lock = threading.Lock()

    # ── 写入 ──────────────────────────────────────────────────

    def add(self, water_hist: list[float], action_hist: list[int], next_water: float) -> None:
        with self._lock:
            self._water.append(list(water_hist))
            self._action.append(list(action_hist))
            self._next.append(float(next_water))

    def add_error(self, predicted: float, actual: float) -> None:
        """记录一次预测误差。两处序列都追加，保证趋势与均值口径一致。"""
        err = abs(predicted - actual)
        with self._lock:
            self._errors.append(err)
            self._trend.append(err)

    # ── 统计 ──────────────────────────────────────────────────

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._water)

    def average_error(self) -> float:
        with self._lock:
            if not self._errors:
                return 0.0
            return float(np.mean(self._errors))

    def error_trend(self) -> float:
        """正数表示误差在变大（模型跟不上），负数表示在收敛。"""
        with self._lock:
            if len(self._trend) < 5:
                return 0.0
            recent = list(self._trend)[-5:]
            older = list(self._trend)[:5]
            return float(np.mean(recent) - np.mean(older))

    # ── 采样 ──────────────────────────────────────────────────

    def sample(self, batch_size: int, cfg: LearningConfig) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor] | None:
        """按「最近样本加权」抽取一个批次。

        这是原版 ``sample_weighted_batch`` 的等价的简化实现：原版注释说要按误差加权，
        但实际代码也只是给最近 N 条乘一个固定倍数，这里保持一致（不做虚假的难例挖掘）。
        """
        with self._lock:
            total = len(self._water)
            if total < batch_size:
                return None
            water = list(self._water)
            action = list(self._action)
            nxt = list(self._next)

        weights = np.ones(total)
        boost_n = min(cfg.recent_window, total)
        weights[-boost_n:] *= cfg.recent_boost
        weights = weights / weights.sum()

        indices = np.random.choice(total, batch_size, replace=False, p=weights)

        batch_water = torch.tensor([water[i] for i in indices], dtype=torch.float32)
        batch_action = torch.tensor([action[i] for i in indices], dtype=torch.float32)
        batch_next = torch.tensor([[nxt[i]] for i in indices], dtype=torch.float32)
        return batch_water, batch_action, batch_next

    def clear(self) -> None:
        with self._lock:
            self._water.clear()
            self._action.clear()
            self._next.clear()


class OnlineLearner:
    """把经验回放接到模型上，边跑边微调。"""

    def __init__(self, runner, cfg: LearningConfig | None = None) -> None:
        self.runner = runner
        self.cfg = cfg or LearningConfig()
        self.memory = ExperienceMemory(self.cfg.memory_size)

        self._optimizer = torch.optim.Adam(runner.model.parameters(), lr=self.cfg.lr)
        self._criterion = nn.MSELoss()
        self._train_lock = threading.Lock()

        self.learn_count = 0
        self.learn_interval = self.cfg.learn_interval_default
        # 每轮学习后保存的损失，用于健康度展示
        self.last_loss: float | None = None

    # ── 核心 ──────────────────────────────────────────────────

    def should_learn(self, step: int) -> bool:
        """按当前自适应间隔判断此刻是否该学一轮。"""
        if step <= 0:
            return False
        return step % self.learn_interval == 0

    def learn(self) -> dict[str, object] | None:
        """执行一轮梯度更新，并据误差调整下一次的学习间隔。

        返回本轮学习摘要；样本不足时返回 ``None``（不消耗 ``learn_count``）。
        """
        batch = self.memory.sample(self.cfg.batch_size, self.cfg)
        if batch is None:
            return None

        batch_water, batch_action, batch_next = batch

        # 训练与推理共用同一个模型实例，必须互斥，
        # 否则并发的 forward 会看到被 optimizer.step() 改到一半的参数
        with self._train_lock:
            water_norm = self.runner.normalize_batch(batch_water)
            next_norm = self.runner.normalize_batch(batch_next)

            self.runner.model.train()
            for _ in range(self.cfg.epochs):
                self._optimizer.zero_grad()
                loss = self._criterion(self.runner.predict_batch(water_norm, batch_action), next_norm)
                loss.backward()
                self._optimizer.step()
            self.runner.model.eval()

            self.last_loss = float(loss.item())
            self.learn_count += 1

        avg_err = self.memory.average_error()
        trend = self.memory.error_trend()
        before = self.learn_interval

        cfg = self.cfg
        if avg_err > cfg.error_high or trend > cfg.trend_high:
            # 模型跟不上当前工况：缩短间隔，学得更勤
            self.learn_interval = max(cfg.learn_interval_min, self.learn_interval - cfg.learn_interval_step)
            reason = "误差偏高，加速学习"
        elif avg_err < cfg.error_low and trend < cfg.trend_low:
            # 已经很准：放长间隔，省算力
            self.learn_interval = min(cfg.learn_interval_max, self.learn_interval + cfg.learn_interval_step)
            reason = "误差收敛，减速学习"
        else:
            reason = "维持当前学习节奏"

        log.info(
            "在线学习 #%d | 损失=%.6f | 平均误差=%.4f m | 趋势=%+.4f | 间隔 %d→%d（%s）",
            self.learn_count, self.last_loss, avg_err, trend,
            before, self.learn_interval, reason,
        )

        return {
            "learnCount": self.learn_count,
            "loss": round(self.last_loss, 6),
            "averageError": round(avg_err, 4),
            "errorTrend": round(trend, 5),
            "learnInterval": self.learn_interval,
            "reason": reason,
        }

    def stats(self) -> dict[str, object]:
        return {
            "learnCount": self.learn_count,
            "learnInterval": self.learn_interval,
            "memorySize": self.memory.size,
            "averageError": round(self.memory.average_error(), 4),
            "errorTrend": round(self.memory.error_trend(), 5),
            "lastLoss": round(self.last_loss, 6) if self.last_loss is not None else None,
            "batchSize": self.cfg.batch_size,
            "epochs": self.cfg.epochs,
            "lr": self.cfg.lr,
        }
