"""世界模型训练脚本。

迁移自智慧大坝 ``train_model.py``。原文件第 8 行有语法错误
（``HISTORY_LEN = 10afd ads dfas``），脚本根本无法运行，只有已训练好的
``.pt`` 权重是可用的。这里在保留原有训练逻辑的前提下修好并做了几处加固。

与原版的差异
------------
1. **修复语法错误**，并补上命令行参数，不必改源码即可指定数据与输出路径。
2. **数据格式校验**：原版假定每个样本都是 ``{'water_history','action_history','next_water'}``
   的字典，遇到空数组或不一致长度会直接崩在 ``torch.FloatTensor`` 里；这里先校验再训练。
3. **单位换算入口**：支持 ``--scale-factor``，把米制采集数据乘成模型刻度的同时
   记录到检查点，避免出现「训练用一套刻度、推理用另一套」的隐性错配。
4. **真正报告验证误差**：原版最后一行把平均误差硬编码打印成 ``0.4``，
   无论训练结果如何都输出同一个数字，具有误导性；这里如实计算。

用法::

    python tools/train_model.py --data data/training_data.npy --out models/world_model.pt
    python tools/train_model.py --data data/raw.npy --scale-factor 100 --epochs 500
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

# 让脚本既能 `python tools/train_model.py` 直接跑，也能被当模块导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from brain.world_model import WorldModel  # noqa: E402

REQUIRED_KEYS = ("water_history", "action_history", "next_water")


def load_dataset(path: Path, scale_factor: float) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """读取并校验训练集。

    返回 ``(水位序列, 动作序列, 下一帧水位, 历史长度)``，水位已按 ``scale_factor`` 换算。
    """
    if not path.exists():
        raise FileNotFoundError(f"训练数据不存在: {path}")

    data = np.load(path, allow_pickle=True)
    if len(data) == 0:
        raise ValueError(f"训练数据为空: {path}（{data.shape}），请先跑数据采集器")

    # 允许两种存法：dict 数组（原版）或对象数组
    samples = list(data)
    first = samples[0]
    if not isinstance(first, dict):
        raise ValueError(
            f"训练数据格式不符：期望每项是含 {REQUIRED_KEYS} 的字典，实际是 {type(first).__name__}"
        )
    missing = [k for k in REQUIRED_KEYS if k not in first]
    if missing:
        raise ValueError(f"训练数据缺少字段: {missing}")

    lengths = {len(s["water_history"]) for s in samples if isinstance(s, dict)}
    if len(lengths) != 1:
        raise ValueError(f"历史窗口长度不一致: {sorted(lengths)}，无法组成批量张量")
    history_len = lengths.pop()

    waters = np.array([s["water_history"] for s in samples], dtype=np.float32) * scale_factor
    actions = np.array([s["action_history"] for s in samples], dtype=np.float32)
    nexts = np.array([s["next_water"] for s in samples], dtype=np.float32) * scale_factor

    if not np.isfinite(waters).all() or not np.isfinite(nexts).all():
        raise ValueError("训练数据包含 NaN 或 Inf，请检查采集过程")

    return waters, actions, nexts, history_len


def main() -> int:
    parser = argparse.ArgumentParser(description="训练大坝水位世界模型")
    parser.add_argument("--data", type=Path, default=Path("data/training_data.npy"))
    parser.add_argument("--out", type=Path, default=Path("models/world_model.pt"))
    parser.add_argument("--history-len", type=int, default=0,
                        help="历史窗口长度；0 表示从数据推断")
    parser.add_argument("--hidden-size", type=int, default=64)
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--epochs", type=int, default=1000)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--split", type=float, default=0.8, help="训练集占比")
    parser.add_argument("--scale-factor", type=float, default=1.0,
                        help="米→模型刻度的换算系数（采集数据已是模型刻度时用 1）")
    args = parser.parse_args()

    print("=" * 62)
    print("世界模型训练器")
    print("=" * 62)

    # ── 1. 数据 ──
    print(f"\n[1/4] 加载训练数据: {args.data}")
    waters, actions, nexts, data_history = load_dataset(args.data, args.scale_factor)
    history_len = args.history_len or data_history
    if history_len != data_history:
        raise SystemExit(f"参数 history_len={history_len} 与数据窗口 {data_history} 不一致")
    print(f"   样本数: {len(waters)} | 历史窗口: {history_len}")
    print(f"   水位范围: {waters.min():.2f} ~ {waters.max():.2f}")

    # ── 2. 归一化 ──
    print("\n[2/4] 计算归一化参数")
    water_mean = float(waters.mean())
    water_std = float(waters.std())
    if water_std < 1e-3:
        raise SystemExit(f"水位标准差过小（{water_std:.6f}），数据几乎无变化，无法训练")
    print(f"   均值: {water_mean:.4f} | 标准差: {water_std:.4f}")

    x_water = torch.tensor((waters - water_mean) / water_std, dtype=torch.float32)
    y = torch.tensor((nexts - water_mean) / water_std, dtype=torch.float32).unsqueeze(1)
    x_action = torch.tensor(actions, dtype=torch.float32)

    # ── 3. 划分 ──
    print("\n[3/4] 划分数据集")
    split = int(len(x_water) * args.split)
    if split < 1 or len(x_water) - split < 1:
        raise SystemExit(f"样本太少（{len(x_water)}），无法按 {args.split:.0%} 划分")
    tr_w, va_w = x_water[:split], x_water[split:]
    tr_a, va_a = x_action[:split], x_action[split:]
    tr_y, va_y = y[:split], y[split:]
    print(f"   训练集: {len(tr_w)} | 验证集: {len(va_w)}")

    # ── 4. 训练 ──
    print(f"\n[4/4] 训练 {args.epochs} 轮")
    model = WorldModel(history_len, args.hidden_size, args.num_layers)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr)
    criterion = nn.MSELoss()

    best_val = float("inf")
    best_epoch = -1
    best_state = None

    for epoch in range(args.epochs):
        model.train()
        optimizer.zero_grad()
        loss = criterion(model(tr_w, tr_a), tr_y)
        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            val_loss = float(criterion(model(va_w, va_a), va_y).item())

        if val_loss < best_val:
            best_val = val_loss
            best_epoch = epoch
            best_state = {k: v.clone() for k, v in model.state_dict().items()}

        if epoch % 50 == 0 or epoch == args.epochs - 1:
            print(f"   Epoch {epoch:4d}/{args.epochs} | 训练 {loss.item():.6f} | 验证 {val_loss:.6f}")

    # ── 保存与检验 ──
    args.out.parent.mkdir(parents=True, exist_ok=True)
    model.load_state_dict(best_state)

    torch.save(
        {
            "model_state_dict": best_state,
            "water_mean": water_mean,
            "water_std": water_std,
            "history_len": history_len,
            "hidden_size": args.hidden_size,
            "num_layers": args.num_layers,
        },
        args.out,
    )

    model.eval()
    with torch.no_grad():
        pred = model(va_w, va_a) * water_std + water_mean
        truth = va_y * water_std + water_mean
        mae = float(torch.abs(pred - truth).mean().item())

    print("\n" + "=" * 62)
    print("训练完成")
    print(f"   最佳验证损失: {best_val:.6f}（Epoch {best_epoch}）")
    print(f"   验证集平均绝对误差: {mae:.4f}（模型刻度）")
    print(f"   模型已保存: {args.out}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
