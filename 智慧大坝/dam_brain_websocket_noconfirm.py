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
PLANNING_HORIZON = 8
NUM_CANDIDATES = 64

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
COST_WASTE = 10.0
COST_SWITCH = 5.0

# ========== 水位参数 ==========
WATER_DEAD = 50
WATER_CRITICAL = 55
WATER_NORMAL_LOW = 55
WATER_NORMAL_HIGH = 80
WATER_WARNING = 80
WATER_WARNING_HIGH = 110
WATER_EMERGENCY = 110
WATER_MAX_VALID = 200

ADD_WATER_AT = 55
ADD_WATER_TO = 65
TARGET_WATER = 65

# ========== 自动模式参数 ==========
AUTO_MODE = True           # 自动模式，无需确认
OPEN_COOLDOWN = 10         # 开闸冷却10秒（避免频繁开关）
OPEN_HOLD_STEPS = 3        # 开闸后保持3步


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
        """预测未来水位序列"""
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
        # 检测并设置计算设备
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"\n{'='*50}")
        print(f"🔧 计算设备配置")
        print(f"   使用设备: {self.device}")
        if torch.cuda.is_available():
            print(f"   显卡型号: {torch.cuda.get_device_name(0)}")
            print(f"   显存容量: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
            print(f"   CUDA版本: {torch.version.cuda}")
        else:
            print(f"   💡 提示: 使用CPU计算")
        print(f"   🤖 模式: 全自动 (无需人工确认)")
        print(f"{'='*50}\n")

        # 加载模型
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

        # 自动模式参数
        self.last_open_time = 0
        self.OPEN_COOLDOWN = OPEN_COOLDOWN
        self.open_hold_steps = OPEN_HOLD_STEPS
        self.open_hold_count = 0
        self.gate_just_opened = False

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

    def predict_future(self, action_seq):
        """预测未来水位序列"""
        water_norm = [(w - self.water_mean) / self.water_std for w in self.water_history]

        water_tensor = torch.FloatTensor([water_norm]).to(self.device)
        action_hist_tensor = torch.FloatTensor([list(self.action_history)]).to(self.device)
        action_seq_tensor = torch.FloatTensor([action_seq]).to(self.device)

        preds_norm = self.model.predict_sequence(
            water_tensor, action_hist_tensor, action_seq_tensor, len(action_seq)
        )

        return [p * self.water_std + self.water_mean for p in preds_norm]

    def predict_next(self):
        """预测下一个水位"""
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
        """计算代价函数"""
        total = 0.0

        if len(self.water_history) >= 5:
            recent = list(self.water_history)[-5:]
            rate = (recent[-1] - recent[0]) / 5
        else:
            rate = 0

        for water in predicted_waters:
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

        total += COST_WASTE * sum(action_seq)
        switches = sum(1 for i in range(1, len(action_seq)) if action_seq[i] != action_seq[i-1])
        total += COST_SWITCH * switches

        return total

    def deep_think(self):
        """深度思考 - 选择最优动作"""
        if len(self.water_history) < HISTORY_LEN:
            return 0

        current = self.water_history[-1]

        # 应急水位强制开闸
        if current >= WATER_EMERGENCY:
            return 1

        # 检查是否需要预防性开闸
        closed_pred = self.predict_future([0] * PLANNING_HORIZON)
        if closed_pred[-1] - current > 2:
            if current > WATER_CRITICAL:
                return 0

        self.think_count += 1

        # 生成候选动作序列
        candidates = []
        for _ in range(NUM_CANDIDATES):
            candidates.append(np.random.randint(0, 2, PLANNING_HORIZON).tolist())
        candidates.append([0] * PLANNING_HORIZON)

        # 批量预测
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

        # 定期输出思考日志
        if self.think_count % 10 == 0:
            current = self.water_history[-1]
            final_pred = self.predict_future(best_seq)[-1]
            level = get_level_name(current)
            avg_error = self.memory.get_average_error()

            if len(self.water_history) >= 5:
                recent = list(self.water_history)[-5:]
                rate = (recent[-1] - recent[0]) / 5
            else:
                rate = 0

            print(f"\n🧠 思考#{self.think_count} | 水位:{current:.0f} {level} | 预测终点:{final_pred:.0f} | 代价:{best_cost:.2f}")
            print(f"   📊 误差:{avg_error:.2f} | 记忆:{self.memory.size()} | 已学:{self.learn_count}次")

            explanation = self.generate_explanation(current, level, best_seq[0], final_pred, best_cost, rate)
            print(f"   💬 {explanation}")

        return best_seq[0]

    def generate_explanation(self, water, level, action, prediction, cost, rate):
        """生成决策解释"""
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
                return f"🚨 应急水位{water}，强制开闸放水！"
            elif water >= WATER_WARNING:
                return f"⚠️ 水位{water}({trend})，自动开闸放水"
            else:
                return f"📈 水位{water}({trend})，预防性开闸"
        else:
            if water <= WATER_CRITICAL:
                return f"🔒 濒死水位{water}，紧急关闸蓄水"
            elif water <= 60:
                return f"🔒 水位偏低{water}，关闸蓄水"
            else:
                return f"✅ 水位{water}({trend})，保持关闸"

    def online_learn(self):
        """在线学习"""
        if self.memory.size() < LEARN_BATCH_SIZE:
            return

        self.learn_count += 1
        print(f"\n📚 [在线学习 #{self.learn_count}]")

        batch = self.memory.sample_batch(LEARN_BATCH_SIZE)
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
        print(f"   ✅ 完成 | 误差:{self.memory.get_average_error():.2f}")

    async def run(self):
        """主运行循环（全自动版本）"""
        print(f"\n{'='*50}")
        print(f"🤖 智能大脑启动（全自动模式）")
        print(f"   连接地址: {WS_URL}")
        print(f"   闸门控制: HTTP GET (自动执行)")
        print(f"   目标水位: {TARGET_WATER}")
        print(f"   开闸冷却: {OPEN_COOLDOWN}秒 | 保持步数: {OPEN_HOLD_STEPS}")
        print(f"   水位体系: 死<{WATER_DEAD} | 濒{WATER_DEAD}-{WATER_CRITICAL} | 正常{WATER_CRITICAL}-{WATER_WARNING} | 预警{WATER_WARNING}-{WATER_WARNING_HIGH} | 应急>{WATER_EMERGENCY}")
        print(f"{'='*50}\n")

        print(f"💧 请加水至 {ADD_WATER_TO} 左右")
        print(f"   系统已就绪，AI将自动控制闸门...\n")

        while True:
            try:
                print(f"[⏳] 正在连接传感器 {WS_URL} ...")
                async with websockets.connect(WS_URL) as websocket:
                    print(f"[✅] 已连接！AI自动模式运行中...\n")

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
                            print(f"\r[初始化] 水位:{water} {get_level_name(water)} [{len(self.water_history)}/{HISTORY_LEN}]", end='', flush=True)
                            if len(self.water_history) == HISTORY_LEN:
                                print(f"\n✅ 初始化完成，起始水位: {water:.0f}")
                                print(f"🤖 AI自动控制已启动\n")
                            continue

                        # 开闸保持逻辑
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
                                print(f"\n   ✅ 开闸保持结束")

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
                            print(f"[✅] 系统继续运行...\n")
                            continue

                        # 记录预测误差
                        if self.last_prediction is not None:
                            self.memory.add_error(self.last_prediction, water)

                        # 存储经验
                        if len(self.water_history) == HISTORY_LEN:
                            self.memory.add(self.water_history, self.action_history, water)

                        # AI决策
                        action = self.deep_think()

                        # 自动执行（带冷却）
                        if action == 1 and self.last_action != 1:
                            now = time.time()
                            if now - self.last_open_time < self.OPEN_COOLDOWN:
                                remaining = int(self.OPEN_COOLDOWN - (now - self.last_open_time))
                                print(f"\r[{time.strftime('%H:%M:%S')}] ⏳ 开闸冷却 {remaining}秒 | 水位:{water:.0f}", end='', flush=True)
                                action = 0
                            else:
                                # 自动开闸
                                self.last_open_time = now
                                self.gate_just_opened = True
                                self.open_hold_count = 0
                                print(f"\n🤖 AI自动决策: 开闸放水")
                                print(f"   当前水位: {water} [{get_level_name(water)}]")

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


# ========== Flask应用（仅用于监控） ==========
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
        'mode': 'auto',
        'current_water': brain_instance.water_history[-1] if brain_instance.water_history else None,
        'current_action': '开闸' if brain_instance.current_action == 1 else '关闸',
        'step_count': brain_instance.step_count,
        'water_cycles': brain_instance.water_cycles,
        'avg_error': brain_instance.memory.get_average_error(),
        'device': str(brain_instance.device),
        'gpu_available': torch.cuda.is_available(),
    })


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
        print(f"   显卡: {torch.cuda.get_device_name(0)}")
    print(f"   🤖 模式: 全自动无需确认")
    print()

    # 启动大脑
    brain = DamBrain(model_path='world_model_improved.pt')
    brain_instance = brain

    # 启动Flask监控线程（可选）
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    print(f"[✅] 监控接口: http://0.0.0.0:{FLASK_PORT}/status")

    # 运行主程序
    try:
        asyncio.run(brain.run())
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 停止运行")
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            print(f"✅ GPU缓存已清理")