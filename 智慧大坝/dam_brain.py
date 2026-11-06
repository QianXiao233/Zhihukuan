import socket
import time
import struct
import numpy as np
import torch
import torch.nn as nn
from collections import deque
import select

# ========== 服务端配置 ==========
LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8082

# ========== 控制参数 ==========
HISTORY_LEN = 10
PLANNING_HORIZON = 12
NUM_CANDIDATES = 256

# ========== 在线学习参数 ==========
LEARN_EVERY_N_STEPS = 50
LEARN_EPOCHS = 5
LEARN_LR = 0.0001
MEMORY_SIZE = 500
LEARN_BATCH_SIZE = 64

# ========== 代价函数权重 ==========
COST_DEAD = 10000.0
COST_CRITICAL = 500.0
COST_LOW = 10.0
COST_WARNING = 30.0
COST_EMERGENCY = 100.0
COST_WASTE = 15.0
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

# ========== 通信帧 ==========
FRAME_OPEN  = bytes.fromhex('AA11010101DBBB')
FRAME_CLOSE = bytes.fromhex('AA11010100DBBB')


def parse_sensor_frame(data: bytes) -> int:
    if len(data) < 13 or data[0] != 0xAA or data[-1] != 0xBB:
        return None
    return struct.unpack('>H', data[4:6])[0]


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
    def __init__(self, model_path='world_model.pt'):
        ckpt = torch.load(model_path, weights_only=False)
        self.model = WorldModel(ckpt['history_len'], ckpt['hidden_size'], ckpt['num_layers'])
        self.model.load_state_dict(ckpt['model_state_dict'])
        self.water_mean = ckpt['water_mean']
        self.water_std = ckpt['water_std']

        self.memory = ExperienceMemory(max_size=MEMORY_SIZE)
        self.optimizer = torch.optim.Adam(self.model.parameters(), lr=LEARN_LR)
        self.criterion = nn.MSELoss()

        self.water_history = deque(maxlen=HISTORY_LEN)
        self.action_history = deque(maxlen=HISTORY_LEN)

        self.server_sock = None
        self.conn = None

        self.think_count = 0
        self.step_count = 0
        self.water_cycles = 0
        self.learn_count = 0
        self.last_prediction = None
        self.current_action = 0
        self.last_action = 0

    def get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "无法获取"

    def wait_for_connection(self):
        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((LISTEN_HOST, LISTEN_PORT))
        self.server_sock.listen(1)
        print(f"[⏳] 等待传感器连接... 本机: {self.get_local_ip()}:{LISTEN_PORT}")
        self.conn, addr = self.server_sock.accept()
        self.conn.setblocking(False)  # 非阻塞模式
        print(f"[✅] 传感器已连接！来自: {addr[0]}:{addr[1]}")

    def read_water_nonblock(self) -> int:
        """非阻塞读取水位，有数据就返回，没数据返回None"""
        try:
            ready, _, _ = select.select([self.conn], [], [], 0.05)
            if ready:
                data = self.conn.recv(1024)
                if not data or len(data) == 0:
                    return None
                water = parse_sensor_frame(data)
                if not is_valid_water(water):
                    return None
                return water
        except (ConnectionResetError, BrokenPipeError, OSError, BlockingIOError):
            pass
        return None

    def read_water_block(self, timeout=3.0) -> int:
        """阻塞读取水位，直到收到有效数据或超时"""
        start = time.time()
        while time.time() - start < timeout:
            water = self.read_water_nonblock()
            if water is not None:
                return water
            time.sleep(0.05)
        return None

    def send_action(self, action: int):
        if action == self.last_action:
            return  # 不重复发送相同命令
        try:
            if action == 1:
                self.conn.send(FRAME_OPEN)
            else:
                self.conn.send(FRAME_CLOSE)
            self.last_action = action
        except Exception:
            pass

    def predict_future(self, action_seq):
        water_norm = [(w - self.water_mean) / self.water_std for w in self.water_history]
        preds_norm = self.model.predict_sequence(water_norm, list(self.action_history), action_seq, len(action_seq))
        return [p * self.water_std + self.water_mean for p in preds_norm]

    def predict_next(self):
        if len(self.water_history) < HISTORY_LEN:
            return None
        water_norm = [(w - self.water_mean) / self.water_std for w in self.water_history]
        self.model.eval()
        with torch.no_grad():
            w = torch.FloatTensor([water_norm])
            a = torch.FloatTensor([list(self.action_history)])
            pred = self.model(w, a).item()
        return pred * self.water_std + self.water_mean

    def compute_cost(self, predicted_waters, action_seq):
        total = 0.0
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
                total += COST_WARNING * ((water - WATER_WARNING) / (WATER_WARNING_HIGH - WATER_WARNING))

        total += COST_WASTE * sum(action_seq)
        switches = sum(1 for i in range(1, len(action_seq)) if action_seq[i] != action_seq[i-1])
        total += COST_SWITCH * switches
        return total

    def deep_think(self):
        if len(self.water_history) < HISTORY_LEN:
            return 0

        self.think_count += 1

        candidates = []
        for _ in range(NUM_CANDIDATES):
            candidates.append(np.random.randint(0, 2, PLANNING_HORIZON).tolist())
        candidates.append([0] * PLANNING_HORIZON)

        best_seq = None
        best_cost = float('inf')

        for seq in candidates:
            pred = self.predict_future(seq)
            cost = self.compute_cost(pred, seq)
            if cost < best_cost:
                best_cost = cost
                best_seq = seq

        if self.think_count % 10 == 0:
            current = self.water_history[-1]
            final_pred = self.predict_future(best_seq)[-1]
            avg_error = self.memory.get_average_error()
            print(f"\n🧠 思考#{self.think_count} | 水位:{current:.0f} | 预测终点:{final_pred:.0f} | 代价:{best_cost:.2f}")
            print(f"   📊 误差:{avg_error:.2f} | 记忆:{self.memory.size()} | 已学:{self.learn_count}次")

        return best_seq[0]

    def online_learn(self):
        if self.memory.size() < LEARN_BATCH_SIZE:
            return

        self.learn_count += 1
        print(f"\n📚 [在线学习 #{self.learn_count}]")

        batch = self.memory.sample_batch(LEARN_BATCH_SIZE)
        if batch is None:
            return

        water_batch, action_batch, next_batch = batch
        water_norm = (water_batch - self.water_mean) / self.water_std
        next_norm = (next_batch - self.water_mean) / self.water_std

        self.model.train()
        for epoch in range(LEARN_EPOCHS):
            self.optimizer.zero_grad()
            loss = self.criterion(self.model(water_norm, action_batch), next_norm)
            loss.backward()
            self.optimizer.step()
        self.model.eval()

        print(f"   ✅ 完成 | 误差:{self.memory.get_average_error():.2f}")

    def run(self):
        print(f"\n{'='*50}")
        print(f"🧠 智能大脑启动")
        print(f"   本机: {self.get_local_ip()}:{LISTEN_PORT}")
        print(f"   目标水位: {TARGET_WATER}")
        print(f"{'='*50}\n")

        self.wait_for_connection()

        print(f"\n💧 请加水至 {ADD_WATER_TO} 左右，按 Enter 开始...")
        input()

        print("[初始化] 等待传感器数据...")
        for i in range(HISTORY_LEN):
            water = self.read_water_block(timeout=10.0)
            if water is None:
                print(f"   ❌ 等待超时")
                return
            self.water_history.append(water)
            self.action_history.append(0)
            self.send_action(0)
            print(f"   [{i+1}/{HISTORY_LEN}] 水位: {water:.0f} {get_level_name(water)}")

        print(f"\n✅ 运行中！初始水位: {self.water_history[-1]:.0f}")
        print(f"   每帧实时显示\n")

        try:
            while True:
                # 非阻塞读水位
                water = self.read_water_nonblock()

                if water is not None:
                    # 检查是否需要加水
                    if water <= ADD_WATER_AT:
                        self.water_cycles += 1
                        print(f"\n💧 [加水] 第{self.water_cycles}次 | 本箱{self.step_count}步 | 误差:{self.memory.get_average_error():.2f}")
                        print(f"   加水至 {ADD_WATER_TO}，按 Enter 继续...")
                        self.send_action(0)
                        self.current_action = 0
                        self.last_action = 0
                        self.step_count = 0
                        input()

                        self.water_history.clear()
                        self.action_history.clear()
                        for _ in range(HISTORY_LEN):
                            w = self.read_water_block(timeout=10.0)
                            if w is not None:
                                self.water_history.append(w)
                                self.action_history.append(0)
                                self.send_action(0)
                        self.last_action = 0
                        print(f"[✅] 新水位: {self.water_history[-1]:.0f}\n")
                        continue

                    # 记录预测误差
                    if self.last_prediction is not None:
                        self.memory.add_error(self.last_prediction, water)

                    # 存入经验库
                    if len(self.water_history) == HISTORY_LEN:
                        self.memory.add(self.water_history, self.action_history, water)

                    # 更新历史
                    self.water_history.append(water)
                    self.action_history.append(self.current_action)
                    self.step_count += 1

                    # 深度思考
                    action = self.deep_think()
                    self.current_action = action

                    # 发送命令
                    self.send_action(action)

                    # 预测下一秒
                    self.last_prediction = self.predict_next()

                    # 在线学习
                    if self.step_count % LEARN_EVERY_N_STEPS == 0 and self.step_count > 0:
                        self.online_learn()

                    # 实时显示
                    level = get_level_name(water)
                    act_str = "开🔓" if action == 1 else "关🔒"
                    err = self.memory.get_average_error()
                    print(f"\r[{time.strftime('%H:%M:%S')}] {act_str} | 水位:{water:.0f} {level} | 误差:{err:.2f} | 第{self.water_cycles}箱 | 步:{self.step_count}", end='', flush=True)

                else:
                    # 没收到数据，短暂休眠避免CPU空转
                    time.sleep(0.05)

        except KeyboardInterrupt:
            print(f"\n\n⏹️ 停止 | 思考:{self.think_count} | 加水:{self.water_cycles} | 学习:{self.learn_count}")

            torch.save({
                'model_state_dict': self.model.state_dict(),
                'water_mean': self.water_mean,
                'water_std': self.water_std,
                'history_len': HISTORY_LEN,
                'hidden_size': 64,
                'num_layers': 2,
            }, 'world_model_improved.pt')
            print(f"[💾] 改进模型已保存至 world_model_improved.pt")

            self.send_action(0)
            self.conn.close()
            self.server_sock.close()


if __name__ == '__main__':
    brain = DamBrain(model_path='world_model.pt')
    brain.run()