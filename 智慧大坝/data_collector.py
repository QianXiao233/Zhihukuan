import socket
import time
import random
import struct
import numpy as np
from collections import deque

# ========== 服务端配置 ==========
LISTEN_HOST = '0.0.0.0'
LISTEN_PORT = 8082

# ========== 采集参数 ==========
HISTORY_LENGTH = 10
COLLECT_SECONDS = 3600
SAVE_FILE = 'training_ata1.npy'
SAVE_INTERVAL = 300

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
INITIAL_FILL_TO = 65

COLLECT_SECONDS = 600          # 只跑10分钟
RANDOM_FILL_MIN = 90           # 加水最低90
RANDOM_FILL_MAX = 110          # 加水最高110
RANDOM_FILL_WEIGHTS = {
    'normal': 0.0,             # 不加正常区间
    'warning': 1.0,            # 全部加预警区间
    'emergency': 0.0,
    'high_warning': 0.0,
}

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


def get_prob_open(water: int) -> float:
    if water <= WATER_CRITICAL:
        return 0.0
    elif water <= 50:
        return 0.05
    elif water <= 60:
        return 0.15
    elif water <= 70:
        return 0.4
    elif water <= 80:
        return 0.6
    elif water <= WATER_WARNING_HIGH:
        return 0.85
    else:
        return 1.0


def random_fill_target() -> int:
    zones = list(RANDOM_FILL_WEIGHTS.keys())
    weights = list(RANDOM_FILL_WEIGHTS.values())
    chosen_zone = random.choices(zones, weights=weights, k=1)[0]
    if chosen_zone == 'normal':
        return random.randint(55, 80)
    elif chosen_zone == 'warning':
        return random.randint(80, 110)
    elif chosen_zone == 'emergency':
        return random.randint(110, 140)
    elif chosen_zone == 'high_warning':
        return random.randint(75, 80)
    return ADD_WATER_TO


class DataCollector:
    def __init__(self):
        self.server_sock = None
        self.conn = None
        self.water_history = deque(maxlen=HISTORY_LENGTH)
        self.action_history = deque(maxlen=HISTORY_LENGTH)
        self.training_data = []
        self.current_action = 0
        self.last_action = -1
        self.frame_count = 0
        self.add_water_count = 0
        self.abnormal_count = 0
        self.last_save_time = 0
        self.current_round = 0
        self.fill_samples_count = 0
        self.water_before_fill = None
        self.zone_samples = {
            '濒死': 0, '正常偏低': 0, '正常偏高': 0, '预警': 0, '应急': 0
        }

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
        print(f"[⏳] 等待传感器连接... 本机IP: {self.get_local_ip()}:{LISTEN_PORT}")
        self.conn, addr = self.server_sock.accept()
        self.conn.settimeout(3.0)
        print(f"[✅] 传感器已连接！来自: {addr[0]}:{addr[1]}")

    def read_water(self) -> int:
        try:
            data = self.conn.recv(1024)
            if not data or len(data) == 0:
                return None
            self.frame_count += 1
            water = parse_sensor_frame(data)
            if not is_valid_water(water):
                self.abnormal_count += 1
                return None
            return water
        except socket.timeout:
            return None
        except (ConnectionResetError, BrokenPipeError, OSError):
            return None

    def send_action(self, action: int):
        if action == self.last_action:
            return
        try:
            if action == 1:
                self.conn.send(FRAME_OPEN)
            else:
                self.conn.send(FRAME_CLOSE)
            self.last_action = action
        except Exception:
            pass

    def save_data(self):
        np.save(SAVE_FILE, self.training_data)
        self.last_save_time = time.time()

    def record_sample(self, water: int):
        if len(self.water_history) == HISTORY_LENGTH:
            self.training_data.append({
                'water_history': list(self.water_history),
                'action_history': list(self.action_history),
                'next_water': water
            })
            self.update_zone_stats(water)

    def record_fill_sample(self, water_before, water_after):
        """记录加水操作样本——动作标记为2"""
        if len(self.water_history) == HISTORY_LENGTH and water_after > water_before:
            self.training_data.append({
                'water_history': list(self.water_history),
                'action_history': [2] * HISTORY_LENGTH,
                'next_water': water_after
            })
            self.fill_samples_count += 1
            return True
        return False

    def update_zone_stats(self, water: int):
        if water <= WATER_CRITICAL:
            self.zone_samples['濒死'] += 1
        elif water <= 65:
            self.zone_samples['正常偏低'] += 1
        elif water <= WATER_NORMAL_HIGH:
            self.zone_samples['正常偏高'] += 1
        elif water <= WATER_WARNING_HIGH:
            self.zone_samples['预警'] += 1
        else:
            self.zone_samples['应急'] += 1

    def update_history(self, water: int):
        self.water_history.append(water)
        self.action_history.append(self.current_action)

    def choose_action(self):
        if len(self.water_history) == 0:
            self.current_action = 0
            return
        current = self.water_history[-1]
        prob = get_prob_open(current)
        old_action = self.current_action
        self.current_action = 1 if random.random() < prob else 0
        if self.current_action != old_action:
            self.send_action(self.current_action)

    def print_status(self, water: int, extra=""):
        level = get_level_name(water)
        act = "开🔓" if self.current_action == 1 else "关🔒"
        total = max(len(self.training_data), 1)
        parts = [f"{z}:{c/total*100:.0f}%" for z, c in self.zone_samples.items()]
        coverage = "|".join(parts)
        print(f"\r[帧{self.frame_count:6d}] 水位:{water:4d} {level} | 闸门:{act} | 样本:{len(self.training_data):6d} | 加水样本:{self.fill_samples_count} | {coverage}{extra}", end='', flush=True)

    def handle_add_water(self, current_water=None):
        self.send_action(0)
        self.current_action = 0
        self.last_action = -1
        target = random_fill_target()
        self.current_round += 1
        self.water_before_fill = current_water

        self.save_data()

        print(f"\n")
        print(f"{'─'*50}")
        print(f"💧 [第{self.current_round}轮加水]")
        print(f"   当前水位: {current_water}")
        print(f"   🎯 本轮加水目标: {target}")
        print(f"   目标区间: [{get_level_name(target)}]")
        print(f"   死水位: {WATER_DEAD} | 濒死线: {WATER_CRITICAL}")
        print(f"   💾 数据已保存（{len(self.training_data)}条样本）")
        print(f"{'─'*50}")

        while True:
            cmd = input("\n先加水，再按 Enter 查看水位，输入 ok 继续: ").strip().lower()
            if cmd == 'ok':
                break

            print("   读取中...")
            water = None
            for _ in range(3):
                w = self.read_water()
                if is_valid_water(w):
                    water = w
                    break
                time.sleep(0.3)

            if water is not None:
                level_name = get_level_name(water)
                diff = water - target
                print(f"   📊 水位: {water:4d} [{level_name}] | 距目标: {diff:+d}")
                if abs(diff) <= 5:
                    print(f"   ✅ 已达到目标水位")
                elif diff < 0:
                    print(f"   ⬆️  还需加水 {abs(diff)}")
                else:
                    print(f"   ⬇️  加多了 {diff}")
            else:
                print(f"   ❌ 未收到有效数据")

        print("   📝 等待水位稳定，记录加水样本...")
        water_after = self.water_before_fill
        for _ in range(10):
            w = self.read_water()
            if w and w > water_after:
                water_after = w
            time.sleep(0.3)

        if water_after and water_after > self.water_before_fill:
            recorded = self.record_fill_sample(self.water_before_fill, water_after)
            if recorded:
                print(f"   📝 已记录加水样本: {self.water_before_fill}→{water_after}（动作类型=2）")
                self.update_zone_stats(water_after)
        else:
            print(f"   ⚠️ 未检测到水位上升，跳过加水样本记录")

        print(f"\n[重新初始化] 清空历史缓冲区...")
        self.water_history.clear()
        self.action_history.clear()
        print(f"   ✅ 第{self.current_round}轮开始\n")

    def run(self):
        print(f"\n{'='*60}")
        print(f"📊 数据采集器启动（TCP服务端版 + 加水样本）")
        print(f"   监听端口: {LISTEN_PORT}")
        print(f"   本机IP: {self.get_local_ip()}")
        print(f"   采集时长: {COLLECT_SECONDS}秒")
        print(f"   动作类型: 0=关闸, 1=开闸, 2=加水")
        print(f"   水位体系:")
        print(f"     死: 0-{WATER_DEAD} | 濒: {WATER_DEAD}-{WATER_CRITICAL}")
        print(f"     正常: {WATER_NORMAL_LOW}-{WATER_NORMAL_HIGH}")
        print(f"     预警: {WATER_WARNING}-{WATER_WARNING_HIGH}")
        print(f"     应急: {WATER_EMERGENCY}+")
        print(f"   随机加水: {RANDOM_FILL_MIN}-{RANDOM_FILL_MAX}")
        print(f"{'='*60}\n")

        self.wait_for_connection()

        print(f"\n💧 请先加水至 {INITIAL_FILL_TO} 左右")
        input("   按 Enter 开始...")

        print("[初始化] 填充历史数据...")
        for i in range(HISTORY_LENGTH):
            water = self.read_water()
            if water is not None:
                self.update_history(water)
                self.send_action(0)
                print(f"   [{i+1}/{HISTORY_LENGTH}] 水位: {water} [{get_level_name(water)}]")
        print(f"[✅] 初始化完成，起始水位: {self.water_history[-1]}\n")
        print(f"⏳ 开始采集...\n")

        self.last_save_time = time.time()
        start_time = time.time()

        try:
            while time.time() - start_time < COLLECT_SECONDS:
                water = self.read_water()
                if water is None:
                    continue

                if water <= ADD_WATER_AT:
                    self.add_water_count += 1
                    self.handle_add_water(water)
                    continue

                self.record_sample(water)
                self.update_history(water)
                self.choose_action()

                extra = ""
                if time.time() - self.last_save_time >= SAVE_INTERVAL:
                    self.save_data()
                    extra = " | 💾已保存"

                self.print_status(water, extra)

        except KeyboardInterrupt:
            print(f"\n\n⏹️ 用户中断")

        elapsed = time.time() - start_time
        self.save_data()
        self.send_action(0)

        fill_count = sum(1 for s in self.training_data if s['action_history'][0] == 2)
        print(f"\n{'='*60}")
        print(f"✅ 采集完成！")
        print(f"   时长: {elapsed:.0f}秒 | 帧数: {self.frame_count}")
        print(f"   总样本: {len(self.training_data)} | 异常: {self.abnormal_count}")
        print(f"   加水: {self.add_water_count}轮 | 加水样本: {fill_count}")
        print(f"   区间覆盖: ")
        total = max(len(self.training_data), 1)
        for zone, count in self.zone_samples.items():
            print(f"     {zone}: {count}条 ({count/total*100:.1f}%)")
        print(f"💾 最终保存至 {SAVE_FILE}")
        print(f"{'='*60}")

        self.conn.close()
        self.server_sock.close()


if __name__ == '__main__':
    collector = DataCollector()
    collector.run()