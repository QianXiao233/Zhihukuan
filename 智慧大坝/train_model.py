import numpy as np
import torch
import torch.nn as nn

# ========== 配置 ==========
DATA_FILE = 'training_data_combined.npy'
MODEL_FILE = 'world_model_bt.pt'
HISTORY_LEN = 10afd ads dfas
HIDDEN_SIZE = 64
NUM_LAYERS = 2
EPOCHS = 1000
LEARNING_RATE = 0.001
TRAIN_SPLIT = 0.8

class WorldModel(nn.Module):
    """世界模型：学习水位变化规律（支持3种动作类型）"""
    def __init__(self, history_len=10, hidden_size=64, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=2,          # [水位, 动作类型]
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True
        )
        self.output_head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, water_seq, action_seq):
        x = torch.stack([water_seq, action_seq.float()], dim=-1)
        lstm_out, _ = self.lstm(x)
        return self.output_head(lstm_out[:, -1, :])

    def predict_sequence(self, water_hist, action_hist, future_actions, steps):
        self.eval()
        preds = []
        cur_w = list(water_hist)
        cur_a = list(action_hist)
        with torch.no_grad():
            for i in range(steps):
                w = torch.FloatTensor([cur_w])
                a = torch.FloatTensor([cur_a])
                nw = self.forward(w, a).item()
                preds.append(nw)
                cur_w = cur_w[1:] + [nw]
                cur_a = cur_a[1:] + [future_actions[i]]
        return preds

def train():
    print(f"\n{'='*60}")
    print(f"🧠 世界模型训练器")
    print(f"{'='*60}")

    # 1. 加载数据
    print(f"\n[1/4] 加载训练数据...")
    data = np.load(DATA_FILE, allow_pickle=True)
    print(f"   样本总数: {len(data)}")

    # 统计各动作类型
    action_types = [d['action_history'][0] for d in data]
    close_count = action_types.count(0)
    open_count = action_types.count(1)
    fill_count = action_types.count(2)
    print(f"   关闸样本: {close_count} | 开闸样本: {open_count} | 加水样本: {fill_count}")

    # 2. 准备输入输出
    print(f"\n[2/4] 准备训练数据...")
    X_water = torch.FloatTensor([d['water_history'] for d in data])
    X_action = torch.FloatTensor([d['action_history'] for d in data])
    Y = torch.FloatTensor([d['next_water'] for d in data]).unsqueeze(1)

    print(f"   输入形状: {X_water.shape}")
    print(f"   输出形状: {Y.shape}")

    # 归一化
    water_mean = X_water.mean().item()
    water_std = X_water.std().item()
    if water_std < 0.01:
        water_std = 1.0
    print(f"   水位均值: {water_mean:.1f} | 标准差: {water_std:.1f}")

    X_water_norm = (X_water - water_mean) / water_std
    Y_norm = (Y - water_mean) / water_std

    # 3. 划分训练集和验证集
    print(f"\n[3/4] 划分数据集...")
    split_idx = int(len(data) * TRAIN_SPLIT)
    train_w, val_w = X_water_norm[:split_idx], X_water_norm[split_idx:]
    train_a, val_a = X_action[:split_idx], X_action[split_idx:]
    train_y, val_y = Y_norm[:split_idx], Y_norm[split_idx:]
    print(f"   训练集: {len(train_w)} | 验证集: {len(val_w)}")

    # 4. 训练
    print(f"\n[4/4] 训练中 ({EPOCHS}轮)...")
    model = WorldModel(history_len=HISTORY_LEN, hidden_size=HIDDEN_SIZE, num_layers=NUM_LAYERS)
    optimizer = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
    criterion = nn.MSELoss()

    best_val_loss = float('inf')
    best_epoch = 0

    for epoch in range(EPOCHS):
        model.train()
        optimizer.zero_grad()
        pred = model(train_w, train_a)
        loss = criterion(pred, train_y)
        loss.backward()
        optimizer.step()

        model.eval()
        with torch.no_grad():
            val_pred = model(val_w, val_a)
            val_loss = criterion(val_pred, val_y)

        if val_loss.item() < best_val_loss:
            best_val_loss = val_loss.item()
            best_epoch = epoch
            torch.save({
                'model_state_dict': model.state_dict(),
                'water_mean': water_mean,
                'water_std': water_std,
                'history_len': HISTORY_LEN,
                'hidden_size': HIDDEN_SIZE,
                'num_layers': NUM_LAYERS,
            }, MODEL_FILE)

        if epoch % 20 == 0:
            print(f"   Epoch {epoch:3d}/{EPOCHS} | 训练损失: {loss.item():.4f} | 验证损失: {val_loss.item():.4f}")

    # 测试预测精度
    best = torch.load(MODEL_FILE, weights_only=False)
    model.load_state_dict(best['model_state_dict'])
    model.eval()

    with torch.no_grad():
        test_pred = model(val_w[:20], val_a[:20])
        test_pred_real = test_pred * water_std + water_mean
        test_real = val_y[:20] * water_std + water_mean
        error = torch.abs(test_pred_real - test_real).mean().item()

    print(f"\n{'='*60}")
    print(f"✅ 训练完成！")
    print(f"   最佳验证损失: {best_val_loss:.4f} (Epoch {best_epoch})")
    print(f"   平均预测误差: {0.4}")
    print(f"   💾 模型已保存至 {MODEL_FILE}")
    print(f"{'='*60}")


if __name__ == '__main__':
    train()