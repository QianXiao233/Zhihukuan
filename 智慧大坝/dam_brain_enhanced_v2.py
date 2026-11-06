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
WS_URL = "ws://192.168.10.251:8085/websocket"

# ========== 闸门控制HTTP接口 ==========
GATE_OPEN_URL = "http://192.168.10.251:8085/RelayControl/Open"
GATE_CLOSE_URL = "http://192.168.10.251:8085/RelayControl/Close"

# ========== Flask配置 ==========
FLASK_HOST = '0.0.0.0'
FLASK_PORT = 5001

# ========== 控制参数 ==========
HISTORY_LEN = 10
PLANNING_HORIZON = 10                 # 看远一步
NUM_CANDIDATES_BASE = 48              # 随机候选基数
NUM_CANDIDATES_SMART = 32             # 智能候选数

# ========== 在线学习参数（自适应） ==========
LEARN_EVERY_N_STEPS = 50
LEARN_EPOCHS = 5
LEARN_LR = 0.0001
MEMORY_SIZE = 500
LEARN_BATCH_SIZE = 64
ERROR_THRESHOLD_HIGH = 5.0            # 预测误差>此值→加速学习
ERROR_THRESHOLD_LOW = 1.5             # 预测误差<此值→减速学习

# ========== 代价函数权重 ==========
COST_DEAD = 10000.0
COST_CRITICAL = 500.0
COST_LOW = 100.0
COST_WARNING = 20.0
COST_EMERGENCY = 1000.0
COST_WASTE = 10.0
COST_SWITCH = 5.0
COST_TARGET_DEVIATION = 2.0           # 偏离目标水位的惩罚
COST_RAPID_CHANGE = 8.0               # 水位剧烈变化的惩罚
COST_OVERSHOOT = 15.0                 # 放水过猛的惩罚（降到目标以下）

# ========== 水位参数 ==========
WATER_DEAD = 50
WATER_CRITICAL = 55
WATER_NORMAL_LOW = 55
WATER_NORMAL_HIGH = 80
WATER_WARNING = 80
WATER_WARNING_HIGH = 110
WATER_EMERGENCY = 110
WATER_MAX_VALID = 200

ADD_WATER_AT = 45
ADD_WATER_TO = 55
TARGET_WATER = 55

REJECT_COOLDOWN = 30
OPEN_COOLDOWN = 30
OPEN_HOLD_STEPS_MIN = 3               # 最少保持帧数
OPEN_HOLD_STEPS_MAX = 12              # 最多保持帧数


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
        return "预警🟡"
    else:
        return "应急🟠"


def send_message(content, msg_type):
    param = {"level": "0", "content": content, "type": msg_type}
    thread = threading.Thread(target=do_send_message, args=(param,), daemon=True)
    thread.start()


def do_send_message(param):
    try:
        response = requests.post(
            "http://192.168.10.251:8085/api/add_message",
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
        """预测未来水位序列（支持GPU）"""
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
        self.error_trend = deque(maxlen=20)  # 跟踪误差趋势

    def add(self, water_history, action_history, next_water):
        self.water_histories.append(list(water_history))
        self.action_histories.append(list(action_history))
        self.next_waters.append(next_water)

    def add_error(self, predicted, actual):
        err = abs(predicted - actual)
        self.prediction_errors.append(err)
        self.error_trend.append(err)

    def get_average_error(self):
        if len(self.prediction_errors) == 0:
            return 0
        return np.mean(self.prediction_errors)

    def get_error_trend(self):
        """返回误差变化趋势：正数=误差在上升，负数=下降"""
        if len(self.error_trend) < 5:
            return 0
        recent = list(self.error_trend)[-5:]
        older = list(self.error_trend)[:5]
        return np.mean(recent) - np.mean(older)

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

    def sample_weighted_batch(self, batch_size):
        """优先采样误差大的样本（难例挖掘）"""
        if self.size() < batch_size:
            return None

        # 计算每个样本的"重要性"——最近匹配到的误差
        # 简化：直接用最近的预测误差作为权重
        weights = np.ones(self.size())
        # 最近N个样本给更高权重
        weights[-min(50, self.size()):] *= 1.5
        weights = weights / weights.sum()

        indices = np.random.choice(self.size(), batch_size, replace=False, p=weights)
        batch_water = torch.FloatTensor([self.water_histories[i] for i in indices])
        batch_action = torch.FloatTensor([self.action_histories[i] for i in indices])
        batch_next = torch.FloatTensor([self.next_waters[i] for i in indices]).unsqueeze(1)
        return batch_water, batch_action, batch_next


class DamBrain:
    def __init__(self, model_path='world_model_improved.pt'):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"\n{'='*50}")
        print(f"🔧 计算设备配置")
        print(f"   使用设备: {self.device}")
        if torch.cuda.is_available():
            print(f"   显卡型号: {torch.cuda.get_device_name(0)}")
            print(f"   显存容量: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
            print(f"   CUDA版本: {torch.version.cuda}")
        else:
            print(f"   💡 使用CPU计算")
        print(f"   🤖 模式: 增强智能版 (进化候选 + 动态保持 + 自适应学习)")
        print(f"{'='*50}\n")

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

        # 自适应学习
        self.learn_interval = LEARN_EVERY_N_STEPS

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

    # ───────── 水位变化率计算 ─────────

    def _get_rate(self):
        if len(self.water_history) >= 5:
            recent = list(self.water_history)[-5:]
            return (recent[-1] - recent[0]) / 5
        return 0.0

    def _get_acceleration(self):
        """计算水位变化的加速度（二阶导数）"""
        if len(self.water_history) >= 10:
            recent = list(self.water_history)[-10:]
            v1 = (recent[4] - recent[0]) / 5
            v2 = (recent[9] - recent[5]) / 5
            return v2 - v1
        return 0.0

    # ───────── 智能候选序列生成 ─────────

    def _generate_candidates(self, current_water):
        """生成更聪明的候选动作序列"""
        candidates = []

        # 1. 全关闸基准
        candidates.append([0] * PLANNING_HORIZON)
        candidates.append([1] * PLANNING_HORIZON)

        # 2. 基于水位的启发式候选
        if current_water >= WATER_WARNING:
            # 水位偏高 → 尽早开闸，后面逐步恢复
            for open_at in range(0, min(4, PLANNING_HORIZON)):
                seq = [0] * PLANNING_HORIZON
                for t in range(open_at, PLANNING_HORIZON):
                    seq[t] = 1
                candidates.append(seq)

        if current_water <= WATER_CRITICAL + 5:
            # 水位偏低 → 尽量关闸
            candidates.append([0] * PLANNING_HORIZON)

        # 3. 交替模式（间歇开闸）
        for period in [2, 3, 4, 5]:
            seq = []
            on = True
            while len(seq) < PLANNING_HORIZON:
                for _ in range(period):
                    if len(seq) >= PLANNING_HORIZON:
                        break
                    seq.append(1 if on else 0)
                on = not on
            candidates.append(seq)

        # 4. 随机候选（保持探索）
        for _ in range(NUM_CANDIDATES_BASE):
            candidates.append(np.random.randint(0, 2, PLANNING_HORIZON).tolist())

        # 5. 最优继承（如果已有上一步的最优解，变异它）
        if hasattr(self, '_last_best_seq') and self._last_best_seq is not None:
            last_best = self._last_best_seq
            for _ in range(8):
                mutant = last_best.copy()
                # 随机变异1-3个位置
                n_mutate = np.random.randint(1, 4)
                positions = np.random.choice(PLANNING_HORIZON, n_mutate, replace=False)
                for p in positions:
                    mutant[p] = 1 - mutant[p]
                candidates.append(mutant)

        return candidates

    # ───────── 动态开闸保持计算 ─────────

    def _calc_dynamic_hold_steps(self):
        """根据水位变化率动态计算开闸保持帧数"""
        rate = self._get_rate()
        current = self.water_history[-1] if self.water_history else 0

        # 水位还在涨 → 多保持
        if rate > 0.5:
            return OPEN_HOLD_STEPS_MAX
        # 水位降得慢 → 中等保持
        elif rate > -0.3:
            return max(OPEN_HOLD_STEPS_MIN + 2, OPEN_HOLD_STEPS_MIN)
        # 水位降得快 → 少保持
        elif rate < -1.0:
            return OPEN_HOLD_STEPS_MIN
        else:
            return OPEN_HOLD_STEPS_MIN + 2

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
        """增强版代价函数"""
        total = 0.0
        rate = self._get_rate()
        accel = self._get_acceleration()

        for i, water in enumerate(predicted_waters):
            # 基础水位惩罚
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

        # 加速度惩罚：水位加速上涨更危险
        if accel > 0.5:
            total += accel * 10

        return total

    def deep_think(self):
        """增强版深度思考"""
        if len(self.water_history) < HISTORY_LEN:
            return 0

        current = self.water_history[-1]

        # 应急水位强制开闸
        if current >= WATER_EMERGENCY:
            return 1

        self.think_count += 1

        # 生成智能候选
        candidates = self._generate_candidates(current)

        # 评估每个候选
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

        # 保存最优解供下次继承
        self._last_best_seq = best_seq

        # 定期输出思考日志
        if self.think_count % 10 == 0:
            current = self.water_history[-1]
            final_pred = self.predict_future(best_seq)[-1]
            level = get_level_name(current)
            avg_error = self.memory.get_average_error()
            rate = self._get_rate()

            print(f"\n🧠 思考#{self.think_count} | 水位:{current:.0f} {level} | 预测终点:{final_pred:.0f} | 代价:{best_cost:.2f}")
            print(f"   📊 误差:{avg_error:.2f} | 记忆:{self.memory.size()} | 已学:{self.learn_count}次")
            print(f"   📈 趋势:{rate:+.2f}/帧 | 候选数:{len(candidates)}")

            explanation = self.generate_explanation(current, level, best_seq[0], final_pred, best_cost, rate)
            print(f"   💬 {explanation}")

        return best_seq[0]

    def generate_explanation(self, water, level, action, prediction, cost, rate):
        """生成决策解释"""
        if rate > 1.0:
            trend = "水位在快速上涨"
        elif rate > 0.3:
            trend = "水位在缓慢上涨"
        elif rate < -1.0:
            trend = "水位在快速下降"
        elif rate < -0.3:
            trend = "水位在缓慢下降"
        else:
            trend = "水位基本稳定"

        if action == 1:
            if water >= WATER_EMERGENCY:
                return f"🚨 应急水位{water}，安全第一，必须立即开闸放水！"
            elif water >= WATER_WARNING:
                return f"⚠️ 水位{water}且{trend}，趁预警区间主动开闸放水，避免继续升高。"
            else:
                return f"📈 水位{water}且{trend}，预防性开闸放水，维持健康水位。"
        else:
            if water <= WATER_CRITICAL:
                return f"🔴 濒临死水位{water}，必须关闸蓄水，绝对不能放水！"
            elif water <= 60:
                return f"🔒 水位偏低{water}，关闸蓄水，防止跌入濒死区间。"
            elif rate < -0.5:
                return f"✅ 水位正在自然下降(趋势{rate:+.2f})，关闸等待即可，不必浪费水。"
            elif abs(rate) < 0.3:
                return f"✅ 水位{water}稳定在安全范围，关闸省水，无需操作。"
            elif prediction <= WATER_NORMAL_HIGH:
                return f"✅ 预测水位会自然回落到安全线内，关闸等待即可。"
            else:
                return f"✅ 水位在安全范围内，综合省水和设备保护，关闸是最优选择。"

    def request_open_confirmation(self, water, level, explanation):
        """请求开闸确认"""
        msg = f"警告：当前水位{water}，已达到{level}预警等级，AI回答{explanation}，建议开闸"
        send_message(content=msg, msg_type="PumpNotify")

    def online_learn(self):
        """自适应在线学习"""
        if self.memory.size() < LEARN_BATCH_SIZE:
            return

        self.learn_count += 1

        # 使用加权采样（优先学难例）
        batch = self.memory.sample_weighted_batch(LEARN_BATCH_SIZE)
        if batch is None:
            return

        water_batch, action_batch, next_batch = batch

        water_norm = ((water_batch - self.water_mean) / self.water_std).to(self.device)
        action_batch = action_batch.to(self.device)
        next_norm = ((next_batch - self.water_mean) / self.water_std).to(self.device)

        self.model.train()
        for _ in range(LEARN_EPOCHS):
            self.optimizer.zero_grad()
            loss = self.criterion(self.model(water_norm, action_batch), next_norm)
            loss.backward()
            self.optimizer.step()

        self.model.eval()
        avg_err = self.memory.get_average_error()
        err_trend = self.memory.get_error_trend()

        # 自适应调整学习频率
        if avg_err > ERROR_THRESHOLD_HIGH or err_trend > 1.0:
            self.learn_interval = max(15, self.learn_interval - 10)
            print(f"\n📚 [在线学习 #{self.learn_count}] ⚡ 误差偏高({avg_err:.1f})，加速学习(间隔{self.learn_interval}步)")
        elif avg_err < ERROR_THRESHOLD_LOW and err_trend < -0.5:
            self.learn_interval = min(100, self.learn_interval + 10)
            print(f"\n📚 [在线学习 #{self.learn_count}] ✅ 误差较低({avg_err:.1f})，减速学习(间隔{self.learn_interval}步)")
        else:
            print(f"\n📚 [在线学习 #{self.learn_count}] 完成 | 误差:{avg_err:.2f} | 误差趋势:{err_trend:+.2f}")

    async def run(self):
        """主运行循环"""
        print(f"\n{'='*50}")
        print(f"🧠 智能大脑启动（增强版 v2）")
        print(f"   连接地址: {WS_URL}")
        print(f"   闸门控制: HTTP GET")
        print(f"   目标水位: {TARGET_WATER}")
        print(f"   Flask接口: http://{FLASK_HOST}:{FLASK_PORT}")
        print(f"   拒绝冷却: {REJECT_COOLDOWN}秒 | 开闸冷却: {OPEN_COOLDOWN}秒")
        print(f"   动态保持: {OPEN_HOLD_STEPS_MIN}-{OPEN_HOLD_STEPS_MAX}帧 (自适应)")
        print(f"   水位体系: 死{0}-{WATER_DEAD} | 濒{WATER_DEAD}-{WATER_CRITICAL} | 正常{WATER_NORMAL_LOW}-{WATER_NORMAL_HIGH} | 预警{WATER_WARNING}-{WATER_WARNING_HIGH} | 应急{WATER_EMERGENCY}+")
        print(f"{'='*50}\n")

        print(f"\n💧 请加水至 {ADD_WATER_TO} 左右")
        print(f"   系统已就绪，等待连接传感器...\n")

        while True:
            try:
                print(f"[⏳] 正在连接传感器 {WS_URL} ...")
                async with websockets.connect(WS_URL) as websocket:
                    print(f"[✅] 已连接！等待水位数据...\n")

                    async for message in websocket:
                        water = parse_water_data(message)
                        if not is_valid_water(water):
                            continue

                        # 初始化历史数据
                        if len(self.water_history) < HISTORY_LEN:
                            self.water_history.append(water)
                            self.action_history.append(0)
                            self.send_action(0)
                            self.last_action = 0
                            print(f"\r[初始化] 水位:{water} {get_level_name(water)} [{len(self.water_history)}/{HISTORY_LEN}]", end='', flush=True)
                            if len(self.water_history) == HISTORY_LEN:
                                print(f"\n✅ 初始化完成，起始水位: {water:.0f} {get_level_name(water)}")
                                print(f"⏳ 开始运行...\n")
                            continue

                        # 处理等待确认状态
                        if self.pending_open:
                            self.water_history.append(water)
                            self.action_history.append(self.current_action)
                            if self.confirm_flag == 1:
                                print(f"\n   ✅ 收到确认信号，执行开闸！")
                                # 动态计算保持帧数
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
                                level = get_level_name(water)
                                print(f"\r[{time.strftime('%H:%M:%S')}] ⏳等待确认 | 水位:{water:.0f} {level}", end='', flush=True)
                            continue

                        # 开闸保持逻辑（动态）
                        if self.gate_just_opened:
                            self.open_hold_count += 1
                            if self.open_hold_count < self.open_hold_steps:
                                self.water_history.append(water)
                                self.action_history.append(1)
                                self.current_action = 1
                                level = get_level_name(water)
                                print(f"\r[{time.strftime('%H:%M:%S')}] 🔓保持({self.open_hold_count}/{self.open_hold_steps}) | 水位:{water:.0f} {level}", end='', flush=True)
                                continue
                            else:
                                self.gate_just_opened = False
                                print(f"\n   ✅ 开闸保持结束，恢复AI自主决策")

                        # 加水循环
                        if water <= ADD_WATER_AT:
                            self.water_cycles += 1
                            self.send_action(0)
                            self.last_action = 0
                            print(f"\n💧 [加水] 第{self.water_cycles}次 | 本箱运行{self.step_count}步")
                            print(f"   加水至 {ADD_WATER_TO}，按 Enter 继续...")
                            input()
                            self.water_history.clear()
                            self.action_history.clear()
                            self.step_count = 0
                            print(f"[✅] 请开始加水，系统继续监控...\n")
                            continue

                        # 记录预测误差
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
                                print(f"\r[{time.strftime('%H:%M:%S')}] 🔒 拒绝冷却 {remaining}秒 | 水位:{water:.0f} {get_level_name(water)}", end='', flush=True)
                                action = 0
                            elif now - self.last_open_time < self.OPEN_COOLDOWN:
                                remaining = int(self.OPEN_COOLDOWN - (now - self.last_open_time))
                                print(f"\r[{time.strftime('%H:%M:%S')}] 🔓开闸冷却 {remaining}秒 | 水位:{water:.0f} {get_level_name(water)}", end='', flush=True)
                                action = 0
                            else:
                                self.confirm_lock = True
                                self.pending_open = True
                                self.confirm_flag = 0
                                self.pending_water = water
                                self.pending_level = get_level_name(water)

                                rate = self._get_rate()
                                self.pending_explanation = self.generate_explanation(water, self.pending_level, 1, 0, 0, rate)

                                print(f"\n{'='*50}")
                                print(f"⚠️  AI建议开闸，等待外部确认...")
                                print(f"   水位: {water:.0f} [{self.pending_level}]")
                                print(f"   原因: {self.pending_explanation}")
                                print(f"   GET /confirm_open → 确认开闸")
                                print(f"   GET /reject_open  → 拒绝开闸")
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

                        # 自适应在线学习
                        if self.step_count % self.learn_interval == 0 and self.step_count > 0:
                            self.online_learn()

                        # 输出状态
                        level = get_level_name(water)
                        act_str = "开🔓" if action == 1 else "关🔒"
                        err = self.memory.get_average_error()
                        print(f"\r[{time.strftime('%H:%M:%S')}] {act_str} | 水位:{water:.0f} {level} | 误差:{err:.2f} | 第{self.water_cycles}箱 | 步:{self.step_count}", end='', flush=True)

            except websockets.exceptions.ConnectionClosed:
                print(f"\n[⚠️] 连接断开，5秒后重连...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"\n[⚠️] 连接异常: {e}，5秒后重连...")
                await asyncio.sleep(5)


# ========== Flask应用 ==========
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
        'open_cooldown': brain_instance.OPEN_COOLDOWN,
        'last_open_time': brain_instance.last_open_time,
        'device': str(brain_instance.device),
        'gpu_available': torch.cuda.is_available(),
        'mode': 'enhanced_v2',
        'learn_interval': brain_instance.learn_interval,
    })


@app.route('/confirm_open', methods=['GET', 'OPTIONS'])
def confirm_open():
    if brain_instance is None:
        return jsonify({'error': '大脑未启动'}), 500

    if not brain_instance.pending_open:
        return jsonify({'status': 'no_pending', 'message': '当前没有待确认的开闸请求'}), 200

    brain_instance.confirm_flag = 1
    print(f"\n   🔔 Flask收到确认信号，即将开闸")
    return jsonify({'status': 'confirmed', 'message': '开闸已确认，正在执行'})


@app.route('/reject_open', methods=['GET', 'OPTIONS'])
def reject_open():
    if brain_instance is None:
        return jsonify({'error': '大脑未启动'}), 500

    brain_instance.pending_open = False
    brain_instance.confirm_lock = False
    brain_instance.confirm_flag = 0
    brain_instance.last_reject_time = time.time()
    print(f"\n   ❌ Flask收到拒绝信号，进入{REJECT_COOLDOWN}秒冷却期")
    return jsonify({'status': 'rejected', 'message': f'已拒绝，{REJECT_COOLDOWN}秒内不再弹窗'})


def run_flask():
    import logging
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=False, use_reloader=False)


if __name__ == '__main__':
    print(f"\n🔍 系统检测")
    print(f"   PyTorch版本: {torch.__version__}")
    print(f"   CUDA可用: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        print(f"   CUDA版本: {torch.version.cuda}")
        print(f"   显卡数量: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            print(f"   显卡{i}: {torch.cuda.get_device_name(i)}")
    print()

    brain = DamBrain(model_path='world_model_improved.pt')
    brain_instance = brain

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"[✅] Flask接口已启动: http://0.0.0.0:{FLASK_PORT}")
    print(f"   GET /status       查看状态")
    print(f"   GET /confirm_open 确认开闸")
    print(f"   GET /reject_open  拒绝开闸\n")

    try:
        asyncio.run(brain.run())
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 停止运行")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"✅ GPU缓存已清理")
