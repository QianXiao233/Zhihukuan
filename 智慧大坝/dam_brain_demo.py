import asyncio
import time
import json
import threading
import numpy as np
import torch
import torch.nn as nn
from collections import deque
import requests
import websockets
from flask import Flask, jsonify

# ========== WebSocket配置 ==========
backend_url="10.53.211.19"
WS_URL = "ws://"+backend_url+":8085/websocket"

# ========== 闸门控制HTTP接口 ==========
GATE_OPEN_URL = "http://"+backend_url+":8085/RelayControl/Open"
GATE_CLOSE_URL = "http://"+backend_url+":8085/RelayControl/Close"

# ========== Flask配置 ==========
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5001

# ========== 控制参数 ==========
HISTORY_LEN = 10
PLANNING_HORIZON = 10                # 看远一步，更好展现预判能力
NUM_CANDIDATES = 48                  # 候选数（部分固定+部分随机）

# ========== 在线学习参数 ==========
LEARN_EVERY_N_STEPS = 50
LEARN_EPOCHS = 5
LEARN_LR = 0.0001
MEMORY_SIZE = 500
LEARN_BATCH_SIZE = 64

# ========== 代价函数权重 ==========
COST_DEAD = 10000.0
COST_CRITICAL = 500.0
COST_LOW = 100.0
COST_WARNING = 20.0
COST_EMERGENCY = 1000.0
COST_WASTE = 30.0                    # ⚡ 展演：提高放水浪费成本（原10→30）
COST_SWITCH = 8.0                    # ⚡ 展演：提高开关切换成本（原5→8）
COST_TARGET_DEVIATION = 2.0          # 偏离目标水位的惩罚
COST_OVERSHOOT = 15.0                # 放水过猛的惩罚（降到目标以下）
COST_RAPID_CHANGE = 8.0              # 水位剧烈变化的惩罚

# ========== 水位参数 ==========
WATER_DEAD = 50
WATER_CRITICAL = 55
WATER_NORMAL_LOW = 55
WATER_NORMAL_HIGH = 80
WATER_WARNING = 80                   # 黄色预警线
WATER_WARNING_HIGH = 110
WATER_EMERGENCY = 110                # 应急水位线
WATER_MAX_VALID = 200

ADD_WATER_AT = 35
ADD_WATER_TO = 55
TARGET_WATER = 55

# ========== 🧪 展演参数（非生产配置） ==========
REJECT_COOLDOWN = 5                  # ⚡ 演示用：拒绝冷却5秒（生产30秒）
OPEN_COOLDOWN = 8                    # ⚡ 演示用：开闸冷却8秒（生产30秒）
OPEN_HOLD_STEPS_MIN = 3              # 最少保持帧数
OPEN_HOLD_STEPS_MAX = 10             # 最多保持帧数


def parse_water_data(raw_data) -> int:
    try:
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode('utf-8')
        raw_data = raw_data.strip()
        data = json.loads(raw_data)
        return int(data[0][0])
    except (json.JSONDecodeError, IndexError, ValueError, TypeError):
        return None


def is_valid_water(water: int) -> bool:
    if water is None:
        return False
    if water < 0 or water > WATER_MAX_VALID:
        return False
    return True


def get_level_name(water: int) -> str:
    if water <= WATER_DEAD:
        return "死水位⚫"
    elif water <= WATER_CRITICAL:
        return "濒死🔴"
    elif water <= WATER_NORMAL_HIGH:
        return "正常🟢"
    elif water <= WATER_WARNING_HIGH:
        return "超汛限水位🟡"
    else:
        return "应急🟠"


def send_message(content, msg_type):
    param = {"level": "0", "content": content, "type": msg_type}
    thread = threading.Thread(target=do_send_message, args=(param,), daemon=True)
    thread.start()


def do_send_message(param):
    try:
        response = requests.post(
            "http://"+backend_url+":8085/api/add_message",
            data=param,
            timeout=10
        )
        print(f"消息成功发送，状态码{response.status_code}")
    except Exception as e:
        print(f"发送失败: {e}")


class WorldModel(nn.Module):
    def __init__(self, history_len=10, hidden_size=64, num_layers=2):
        super().__init__()
        self.history_len = history_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        self.lstm = nn.LSTM(input_size=2, hidden_size=hidden_size,
                            num_layers=num_layers, batch_first=True)
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

        if torch.is_tensor(water_hist):
            cur_w = water_hist.cpu().numpy().tolist()[0]
        else:
            cur_w = water_hist

        if torch.is_tensor(action_hist):
            cur_a = action_hist.cpu().numpy().tolist()[0]
        else:
            cur_a = action_hist

        if torch.is_tensor(future_actions):
            future = future_actions.cpu().numpy().tolist()[0]
        else:
            future = future_actions

        device = next(self.parameters()).device

        with torch.no_grad():
            for i in range(steps):
                w_tensor = torch.FloatTensor([cur_w]).to(device)
                a_tensor = torch.FloatTensor([cur_a]).to(device)
                nw = self.forward(w_tensor, a_tensor).item()
                preds.append(nw)
                cur_w = cur_w[1:] + [nw]
                cur_a = cur_a[1:] + [future[i]]
        return preds


class ExperienceMemory:
    def __init__(self, max_size=500):
        self.water_histories = deque(maxlen=max_size)
        self.action_histories = deque(maxlen=max_size)
        self.next_waters = deque(maxlen=max_size)
        self.prediction_errors = deque(maxlen=100)

    def add(self, water_history, action_history, next_water):
        self.water_histories.append(list(water_history))
        self.action_histories.append(list(action_history))
        self.next_waters.append(next_water)

    def add_error(self, predicted, actual):
        self.prediction_errors.append(abs(predicted - actual))

    def get_average_error(self):
        if len(self.prediction_errors) == 0:
            return 0
        return np.mean(self.prediction_errors)

    def size(self):
        return len(self.water_histories)

    def sample_batch(self, batch_size):
        if self.size() < batch_size:
            return None
        indices = np.random.choice(self.size(), batch_size, replace=False)
        batch_water = torch.FloatTensor([self.water_histories[i] for i in indices])
        batch_action = torch.FloatTensor([self.action_histories[i] for i in indices])
        batch_next = torch.FloatTensor([self.next_waters[i] for i in indices]).unsqueeze(1)
        return batch_water, batch_action, batch_next


class DamBrain:
    def __init__(self, model_path='world_model_improved.pt'):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        # print(f"\n{'='*50}")
        # print(f"🧪 智御安澜 · 展演专用版")
        # print(f"{'='*50}")
        # print(f"🔧 计算设备: {self.device}")
        # if torch.cuda.is_available():
        #     print(f"   显卡: {torch.cuda.get_device_name(0)}")
        # print(f"📋 展演场景:")
        # print(f"   场景一: 暴雨快速注水 → 预警线80之前开闸")
        # print(f"   场景二: 小雨缓慢注水 → 应急线110之前开闸")
        # print(f"   场景三: 开闸后动态保持时长")
        # print(f"{'='*50}\n")

        ckpt = torch.load(model_path, weights_only=False, map_location=self.device)
        self.model = WorldModel(ckpt['history_len'], ckpt['hidden_size'], ckpt['num_layers'])
        self.model.load_state_dict(ckpt['model_state_dict'])
        self.model = self.model.to(self.device)
        self.water_mean = ckpt['water_mean']
        self.water_std = ckpt['water_std']

        self.memory = ExperienceMemory(max_size=MEMORY_SIZE)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=LEARN_LR)
        self.criterion = nn.MSELoss()

        self.water_history = deque(maxlen=HISTORY_LEN)
        self.action_history = deque(maxlen=HISTORY_LEN)

        self.think_count = 0
        self.step_count = 0
        self.water_cycles = 0
        self.learn_count = 0
        self.last_prediction = None
        self.current_action = 0
        self.last_action = -1

        self.confirm_flag = 0
        self.pending_open = False
        self.confirm_lock = False
        self.last_reject_time = 0
        self.REJECT_COOLDOWN = REJECT_COOLDOWN
        self.pending_water = 0
        self.pending_level = ""
        self.pending_explanation = ""

        self.last_open_time = 0
        self.OPEN_COOLDOWN = OPEN_COOLDOWN
        self.open_hold_steps = OPEN_HOLD_STEPS_MIN
        self.open_hold_count = 0
        self.gate_just_opened = False

        # 展演场景标记（用于日志输出、更清晰的演示回显）
        self.demo_scenario = "等待注水..."

    def send_action(self, action: int):
        if action == self.last_action:
            return
        url = GATE_OPEN_URL if action == 1 else GATE_CLOSE_URL
        try:
            requests.get(url, timeout=2)
            self.last_action = action
            act_name = "开闸🔓" if action == 1 else "关闸🔒"
            print(f"\n   ✅ 已执行: {act_name}")
        except Exception as e:
            print(f"\n[⚠️] 闸门控制失败: {e}")

    # ───────── 水位变化率 ─────────

    def _get_rate(self):
        if len(self.water_history) >= 5:
            recent = list(self.water_history)[-5:]
            return (recent[-1] - recent[0]) / 5
        return 0.0

    # ───────── 动态保持帧数 ─────────

    def _calc_dynamic_hold_steps(self):
        """根据水位变化率动态计算开闸保持帧数"""
        rate = self._get_rate()
        if rate > 0.5:
            return OPEN_HOLD_STEPS_MAX      # 还在涨 → 多放
        elif rate > -0.3:
            return OPEN_HOLD_STEPS_MIN + 3   # 降得慢 → 中等
        elif rate < -1.0:
            return OPEN_HOLD_STEPS_MIN       # 降得快 → 少放
        else:
            return OPEN_HOLD_STEPS_MIN + 2

    # ───────── 生成候选（含固定策略保证演示稳定） ─────────

    def _generate_candidates_demo(self, current_water):
        """
        🧪 展演专用候选生成：
        根据当前水位状态，智能决定是否加入开闸候选。
        - 水位正常 + 趋势稳定 → 只留关闸候选（不需要考虑开闸）
        - 水位偏高或上涨快 → 加入固定开闸策略
        """
        rate = self._get_rate()
        candidates = []

        # 全关闸基准（永远存在）
        candidates.append([0] * PLANNING_HORIZON)

        # ═══ 判断是否需要考虑开闸 ═══
        # 只有水位偏高(>=预警线) 或 上涨速度快 时，才加入开闸候选
        need_open = (current_water >= WATER_WARNING or
                     current_water >= WATER_CRITICAL + 5 and rate > 0.5 or
                     rate > 1.0)

        if need_open:
            # 【策略1】立刻开闸，保持几帧后关闭
            for keep in [2, 3, 4, 5, 6]:
                seq = [1] * min(keep, PLANNING_HORIZON) + [0] * (PLANNING_HORIZON - keep)
                candidates.append(seq)

            # 【策略2】延迟1-2帧后开闸，再关闭
            for delay in [1, 2]:
                for keep in [3, 4, 5]:
                    seq = [0] * delay + [1] * keep + [0] * (PLANNING_HORIZON - delay - keep)
                    if len(seq) == PLANNING_HORIZON:
                        candidates.append(seq)

            # 【策略3】全开闸基准
            candidates.append([1] * PLANNING_HORIZON)

            # 【策略4】间歇开闸（开-关-开-关）
            for on_period in [2, 3, 4]:
                for off_period in [2, 3, 4]:
                    seq = []
                    toggle = False
                    while len(seq) < PLANNING_HORIZON:
                        for _ in range(on_period if toggle else off_period):
                            if len(seq) >= PLANNING_HORIZON:
                                break
                            seq.append(1 if toggle else 0)
                        toggle = not toggle
                    candidates.append(seq)

        # ═══ 随机候选（保留探索能力） ═══
        if need_open:
            # 需要开闸 → 正常随机探索
            for _ in range(NUM_CANDIDATES):
                candidates.append(np.random.randint(0, 2, PLANNING_HORIZON).tolist())
            # 最优继承
            if hasattr(self, '_last_best_seq') and self._last_best_seq is not None:
                for _ in range(6):
                    mutant = self._last_best_seq.copy()
                    n_mutate = np.random.randint(1, 3)
                    positions = np.random.choice(PLANNING_HORIZON, n_mutate, replace=False)
                    for p in positions:
                        mutant[p] = 1 - mutant[p]
                    candidates.append(mutant)
        else:
            # 不需要开闸 → 随机候选只生成全0序列，不给任何开闸机会
            for _ in range(NUM_CANDIDATES):
                candidates.append([0] * PLANNING_HORIZON)
            # 最优继承也强制归零
            self._last_best_seq = [0] * PLANNING_HORIZON

        return candidates

    def predict_future(self, action_seq):
        water_norm = [(w - self.water_mean) / self.water_std for w in self.water_history]

        water_tensor = torch.FloatTensor([water_norm]).to(self.device)
        action_hist_tensor = torch.FloatTensor([list(self.action_history)]).to(self.device)
        action_seq_tensor = torch.FloatTensor([action_seq]).to(self.device)

        preds_norm = self.model.predict_sequence(
            water_tensor, action_hist_tensor, action_seq_tensor, len(action_seq)
        )

        return [p * self.water_std + self.water_mean for p in preds_norm]

    def predict_next(self):
        if len(self.water_history) < HISTORY_LEN:
            return None

        water_norm = [(w - self.water_mean) / self.water_std for w in self.water_history]

        self.model.eval()
        with torch.no_grad():
            w = torch.FloatTensor([water_norm]).to(self.device)
            a = torch.FloatTensor([list(self.action_history)]).to(self.device)
            pred = self.model(w, a).item()

        return pred * self.water_std + self.water_mean

    def compute_cost(self, predicted_waters, action_seq):
        """
        代价函数负责告诉AI：
          - 水位冲到预警/应急 → 大额罚单
          - 放水浪费水 → 小额罚款
          - 放过头降到死水位 → 巨额罚款
          - 频繁开关闸 → 罚款

        AI的工作：在所有方案中，找到总罚款最小的那个。
        """
        total = 0.0
        rate = self._get_rate()

        for i, water in enumerate(predicted_waters):
            if water <= WATER_DEAD:
                total += COST_DEAD
            elif water <= WATER_CRITICAL:
                total += COST_CRITICAL * ((WATER_CRITICAL - water) / (WATER_CRITICAL - WATER_DEAD)) ** 2
            elif water < WATER_NORMAL_LOW:
                total += COST_LOW * ((WATER_NORMAL_LOW - water) / (WATER_NORMAL_LOW - WATER_CRITICAL))
            elif water >= WATER_EMERGENCY:
                total += COST_EMERGENCY * ((water - WATER_EMERGENCY) / 30) ** 2
            elif water >= WATER_WARNING:
                if rate > 1.0:
                    total += COST_WARNING * 2 * ((water - WATER_WARNING) / (WATER_WARNING_HIGH - WATER_WARNING))
                elif rate > 0.3:
                    total += COST_WARNING * ((water - WATER_WARNING) / (WATER_WARNING_HIGH - WATER_WARNING))
                else:
                    total += COST_WARNING * 0.5 * ((water - WATER_WARNING) / (WATER_WARNING_HIGH - WATER_WARNING))

            # 偏离目标水位的惩罚
            target_dev = abs(water - TARGET_WATER)
            if target_dev > 10:
                total += COST_TARGET_DEVIATION * (target_dev - 10)

            # 超调惩罚：放水放太多降到目标以下
            if action_seq[i] == 1 and i > 0:
                if water < TARGET_WATER:
                    total += COST_OVERSHOOT * (TARGET_WATER - water) / 10

            # 水位剧烈变化惩罚（保护设备）
            if i > 0:
                change = abs(predicted_waters[i] - predicted_waters[i-1])
                if change > 3:
                    total += COST_RAPID_CHANGE * (change - 3)

        # 放水浪费代价
        total += COST_WASTE * sum(action_seq)

        # 开关切换代价
        switches = sum(1 for i in range(1, len(action_seq)) if action_seq[i] != action_seq[i-1])
        total += COST_SWITCH * switches

        return total

    def deep_think(self):
        """
        🧠 深度思考：
        1. 如果水位已到应急 → 强制开闸（安全兜底）
        ✅ 2. 修复了原版的bug：预测到不开闸水位会急剧上涨 → 提前开闸
        3. 生成候选序列 → 预测每种方案的结果 → 选代价最小的
        """
        if len(self.water_history) < HISTORY_LEN:
            return 0

        current = self.water_history[-1]

        # 应急水位 → 强制开闸（不可绕过）
        if current >= WATER_EMERGENCY:
            print(f"\n   🚨 应急水位{current}，强制开闸！")
            return 1

        # ============================================================
        # ✅ 安全守卫：根据水位和上涨速度决定是否需要考虑开闸
        #    · 水位 < 80           → 只有快速上涨(rate>=1.0)才可能开闸
        #    · 水位 80~100（预警区间）→ 上涨慢(rate<1.0)不开，先观察
        #    · 水位 ≥ 100          → 预测可能冲上应急，放行到候选搜索
        #    · 水位 ≥ 110          → 应急，强制开闸
        # ============================================================
        rate = self._get_rate()
        if current < WATER_WARNING:
            # 低于预警线
            if rate < 1.0:
                return 0
        elif current < WATER_EMERGENCY - 10:
            # 预警区间 (80~100)：上涨慢就不开，等到接近应急再考虑
            if rate < 1.0:
                return 0

        # ============================================================
        # ✅ 关键修复：原版这里写的是 return 0（bug）
        #    逻辑是：如果不开闸水位会涨超过2 → 应该提前开闸（return 1）
        # ============================================================
        closed_pred = self.predict_future([0] * PLANNING_HORIZON)
        if closed_pred[-1] - current > 2 and current > WATER_CRITICAL:
            # ☝️ 原版这里是 return 0，导致"该提前开闸反而关闸"
            #    修复为 return 1，让AI在发现危险趋势时提前干预
            if current >= WATER_WARNING:
                # 已经超过预警线且还在涨 → 提前开闸
                pass  # 让下面的候选搜索决定最优时机
            elif closed_pred[-1] >= WATER_EMERGENCY:
                # 预测会冲上应急水位 → 直接提前开闸，不等候选了
                print(f"\n   📈 预测水位将冲到{closed_pred[-1]:.0f}(应急线{WATER_EMERGENCY})，提前开闸！")
                return 1

        self.think_count += 1

        # 生成候选（含固定策略，确保演示稳定）
        candidates = self._generate_candidates_demo(current)

        best_seq = None
        best_cost = float('inf')

        batch_size = 32
        for i in range(0, len(candidates), batch_size):
            batch_candidates = candidates[i:i+batch_size]
            for seq in batch_candidates:
                pred = self.predict_future(seq)
                cost = self.compute_cost(pred, seq)
                if cost < best_cost:
                    best_cost = cost
                    best_seq = seq

        self._last_best_seq = best_seq

        # 定期输出思考日志（展演时可观察AI决策过程）
        if self.think_count % 10 == 0:
            current = self.water_history[-1]
            final_pred = self.predict_future(best_seq)[-1]
            level = get_level_name(current)
            avg_error = self.memory.get_average_error()
            rate = self._get_rate()

            print(f"\n🧠 思考#{self.think_count} | 水位:{current:.0f} {level} | 预测终点:{final_pred:.0f}")
            print(f"   📊 误差:{avg_error:.2f} | 趋势:{rate:+.2f}/帧")

            explanation = self.generate_explanation(current, level, best_seq[0], final_pred, rate)
            print(f"   💬 {explanation}")

        return best_seq[0]

    def generate_explanation(self, water, level, action, prediction, rate):
        """生成展演用决策解释（中文，清晰易懂）"""
        if rate > 1.0:
            trend = "快速上涨"
        elif rate > 0.3:
            trend = "缓慢上涨"
        elif rate < -1.0:
            trend = "快速下降"
        elif rate < -0.3:
            trend = "缓慢下降"
        else:
            trend = "基本稳定"

        if action == 1:
            if water >= WATER_EMERGENCY:
                return f"🚨 应急水位！强制开闸放水，安全第一！"
            elif water >= WATER_WARNING:
                return f"⚠️ ({trend})，已超预警线，主动开闸放水！"
            elif prediction >= WATER_EMERGENCY:
                return f"📈 ({trend})，预测将冲上应急水位，提前开闸！"
            else:
                return f"📈 ({trend})，预防性开闸，保持健康水位。"
        else:
            if water <= WATER_CRITICAL:
                return f"🔴 濒死水位{water}，关闸蓄水保水！"
            elif water <= 60:
                return f"🔒 水位偏低{water}，关闸蓄水。"
            elif prediction <= WATER_NORMAL_HIGH:
                return f"✅ 预测水位会自然回落安全线内，关闸等待。"
            else:
                return f"✅ 当前安全，关闸省水。"

    def request_open_confirmation(self, water, level, explanation):
        msg = f"{explanation}"
        send_message(content=msg, msg_type="PumpNotify")

    def online_learn(self):
        # if self.memory.size() < LEARN_BATCH_SIZE:
        #     return
        # self.learn_count += 1
        # batch = self.memory.sample_batch(LEARN_BATCH_SIZE)
        # if batch is None:
        #     return
        # water_batch, action_batch, next_batch = batch
        # water_norm = ((water_batch - self.water_mean) / self.water_std).to(self.device)
        # action_batch = action_batch.to(self.device)
        # next_norm = ((next_batch - self.water_mean) / self.water_std).to(self.device)
        # self.model.train()
        # for _ in range(LEARN_EPOCHS):
        #     self.optimizer.zero_grad()
        #     loss = self.criterion(self.model(water_norm, action_batch), next_norm)
        #     loss.backward()
        #     self.optimizer.step()
        # self.model.eval()
        # print(f"\n📚 [在线学习 #{self.learn_count}] 完成 | 误差:{self.memory.get_average_error():.2f}")
        pass

    async def run(self):
        """主运行循环"""
        # print(f"\n{'='*50}")
        # print(f"🧠 智能大脑启动（展演专用版）")
        # print(f"{'='*50}")
        # print(f"   地址: {WS_URL}")
        # print(f"   目标水位: {TARGET_WATER}")
        # print(f"   黄色预警线: {WATER_WARNING}")
        # print(f"   应急水位线: {WATER_EMERGENCY}")
        # print(f"   🧪 冷却时间: 拒绝{REJECT_COOLDOWN}s / 开闸{OPEN_COOLDOWN}s")
        # print(f"   🧪 动态保持: {OPEN_HOLD_STEPS_MIN}-{OPEN_HOLD_STEPS_MAX}帧")
        # print(f"{'='*50}\n")
        #
        # print(f"\n💧 请加至{TARGET_WATER}附近，系统就绪...\n")

        while True:
            try:
                print(f"[⏳] 连接传感器 {WS_URL} ...")
                async with websockets.connect(WS_URL) as websocket:
                    print(f"[✅] 已连接！\n")

                    async for message in websocket:
                        water = parse_water_data(message)
                        if not is_valid_water(water):
                            continue

                        # 初始化
                        if len(self.water_history) < HISTORY_LEN:
                            self.water_history.append(water)
                            self.action_history.append(0)
                            self.send_action(0)
                            self.last_action = 0
                            print(f"\r[初始化] {water} {get_level_name(water)} [{len(self.water_history)}/{HISTORY_LEN}]", end='', flush=True)
                            if len(self.water_history) == HISTORY_LEN:
                                print(f"\n✅ 初始化完成，起始水位: {water}")
                            continue

                        # 等待确认
                        if self.pending_open:
                            self.water_history.append(water)
                            self.action_history.append(self.current_action)
                            if self.confirm_flag == 1:
                                print(f"\n   ✅ 收到确认，执行开闸！")
                                self.open_hold_steps = self._calc_dynamic_hold_steps()
                                print(f"   📐 动态保持: {self.open_hold_steps}帧")
                                self.send_action(1)
                                self.current_action = 1
                                self.confirm_flag = 0
                                self.pending_open = False
                                self.confirm_lock = False
                                self.last_open_time = time.time()
                                self.gate_just_opened = True
                                self.open_hold_count = 0
                            else:
                                print(f"\r[{time.strftime('%H:%M:%S')}] ⏳等待确认 | 水位:{water}", end='', flush=True)
                            continue

                        # 开闸保持（动态）
                        if self.gate_just_opened:
                            self.open_hold_count += 1
                            if self.open_hold_count < self.open_hold_steps:
                                self.water_history.append(water)
                                self.action_history.append(1)
                                self.current_action = 1
                                level = get_level_name(water)
                                print(f"\r[{time.strftime('%H:%M:%S')}] 🔓保持({self.open_hold_count}/{self.open_hold_steps}) | 水位:{water} {level}", end='', flush=True)
                                continue
                            else:
                                self.gate_just_opened = False
                                print(f"\n   ✅ 保持结束，AI恢复决策")

                        # 加水循环
                        if water <= ADD_WATER_AT:
                            self.water_cycles += 1
                            self.send_action(0)
                            self.last_action = 0
                            print(f"\n💧 [加水] 第{self.water_cycles}次 | 步数:{self.step_count}")
                            print(f"   加水至{ADD_WATER_TO}，按Enter继续...")
                            input()
                            self.water_history.clear()
                            self.action_history.clear()
                            self.step_count = 0
                            continue

                        # 预测误差记录
                        if self.last_prediction is not None:
                            self.memory.add_error(self.last_prediction, water)

                        # 存储经验
                        if len(self.water_history) == HISTORY_LEN:
                            self.memory.add(self.water_history, self.action_history, water)

                        # AI决策
                        action = self.deep_think()

                        # 开闸确认逻辑
                        if action == 1 and self.last_action != 1:
                            now = time.time()
                            if self.confirm_lock:
                                action = 0
                            elif now - self.last_reject_time < self.REJECT_COOLDOWN:
                                remaining = int(self.REJECT_COOLDOWN - (now - self.last_reject_time))
                                print(f"\r[{time.strftime('%H:%M:%S')}] 🔒 拒绝冷却 {remaining}s | 水位:{water}", end='', flush=True)
                                action = 0
                            elif now - self.last_open_time < self.OPEN_COOLDOWN:
                                remaining = int(self.OPEN_COOLDOWN - (now - self.last_open_time))
                                print(f"\r[{time.strftime('%H:%M:%S')}] 🔓开闸冷却 {remaining}s | 水位:{water}", end='', flush=True)
                                action = 0
                            else:
                                self.confirm_lock = True
                                self.pending_open = True
                                self.confirm_flag = 0
                                self.pending_water = water
                                self.pending_level = get_level_name(water)
                                rate = self._get_rate()
                                self.pending_explanation = self.generate_explanation(water, self.pending_level, 1, 0, rate)

                                print(f"\n{'='*50}")
                                print(f"⚠️  AI建议开闸，等待确认...")
                                print(f"   水位: {water} [{self.pending_level}]")
                                print(f"   原因: {self.pending_explanation}")
                                print(f"   GET /confirm_open → 确认")
                                print(f"   GET /reject_open  → 拒绝")
                                print(f"{'='*50}")

                                self.request_open_confirmation(water, self.pending_level, self.pending_explanation)
                                self.water_history.append(water)
                                self.action_history.append(self.current_action)
                                self.step_count += 1
                                continue

                        # 执行动作
                        self.current_action = action
                        self.send_action(action)
                        self.water_history.append(water)
                        self.action_history.append(action)
                        self.step_count += 1
                        self.last_prediction = self.predict_next()

                        # 在线学习
                        if self.step_count % LEARN_EVERY_N_STEPS == 0 and self.step_count > 0:
                            self.online_learn()

                        level = get_level_name(water)
                        act_str = "开🔓" if action == 1 else "关🔒"
                        err = self.memory.get_average_error()
                        print(f"\r[{time.strftime('%H:%M:%S')}] {act_str} | 水位:{water} {level} | 误差:{err:.2f} | 第{self.water_cycles}箱 | 步:{self.step_count}", end='', flush=True)

            except websockets.exceptions.ConnectionClosed:
                print(f"\n[⚠️] 断开，5秒后重连...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"\n[⚠️] 异常: {e}，5秒后重连...")
                await asyncio.sleep(5)


# ========== Flask ==========
brain_instance = None
app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response


@app.route('/status', methods=['GET', 'OPTIONS'])
def get_status():
    if brain_instance is None:
        return jsonify({'error': '大脑未启动'}), 500
    return jsonify({
        'pending_open': brain_instance.pending_open,
        'confirm_flag': brain_instance.confirm_flag,
        'water': brain_instance.pending_water,
        'level': brain_instance.pending_level,
        'explanation': brain_instance.pending_explanation,
        'current_water': brain_instance.water_history[-1] if brain_instance.water_history else None,
        'current_action': '开闸' if brain_instance.current_action == 1 else '关闸',
        'step_count': brain_instance.step_count,
        'water_cycles': brain_instance.water_cycles,
        'avg_error': brain_instance.memory.get_average_error(),
        'device': str(brain_instance.device),
        'gpu_available': torch.cuda.is_available(),
        'mode': 'demo_v3',
    })


@app.route('/confirm_open', methods=['GET', 'OPTIONS'])
def confirm_open():
    if brain_instance is None:
        return jsonify({'error': '大脑未启动'}), 500
    if not brain_instance.pending_open:
        return jsonify({'status': 'no_pending', 'message': '无待确认请求'}), 200
    brain_instance.confirm_flag = 1
    print(f"\n   🔔 Flask收到确认，即将开闸")
    return jsonify({'status': 'confirmed', 'message': '确认成功'})


@app.route('/reject_open', methods=['GET', 'OPTIONS'])
def reject_open():
    if brain_instance is None:
        return jsonify({'error': '大脑未启动'}), 500
    brain_instance.pending_open = False
    brain_instance.confirm_lock = False
    brain_instance.confirm_flag = 0
    brain_instance.last_reject_time = time.time()
    print(f"\n   ❌ Flask收到拒绝，冷却{REJECT_COOLDOWN}秒")
    return jsonify({'status': 'rejected', 'message': f'已拒绝'})


def run_flask():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False)


if __name__ == '__main__':
    print(f"\n🔍 系统检测")
    print(f"   PyTorch: {torch.__version__}")
    print(f"   CUDA可用: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   CUDA: {torch.version.cuda}")
    print()

    brain = DamBrain(model_path='world_model_improved.pt')
    brain_instance = brain

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"[✅] Flask端口: {FLASK_PORT}")
    print(f"   GET /status       状态")
    print(f"   GET /confirm_open 确认开闸")
    print(f"   GET /reject_open  拒绝开闸\n")

    try:
        asyncio.run(brain.run())
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 停止")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
