"""
data_collector.py - 数据采集器（WebSocket客户端 + HTTP版）
连接传感器WebSocket接收水位数据，HTTP GET控制闸门
随机加水目标，覆盖全水位区间
"""
import asyncio
import time
import random
import json
import numpy as np
from collections import deque
import requests
import websockets

# ========== WebSocket配置 ==========
WS_URL = "ws://192.168.10.251:8085/websocket"

# ========== 闸门控制HTTP接口 ==========
GATE_OPEN_URL = "http://192.168.10.251:8085/RelayControl/Open"
GATE_CLOSE_URL = "http://192.168.10.251:8085/RelayControl/Close"

# ========== 采集参数 ==========
HISTORY_LENGTH = 10
COLLECT_SECONDS = 3600
SAVE_FILE = 'training_data.npy'
SAVE_INTERVAL = 300

# ========== 水位参数 ==========
WATER_DEAD = 50
WATER_CRITICAL = 55
WATER_NORMAL_LOW = 45
WATER_NORMAL_HIGH = 80
WATER_WARNING = 80
WATER_WARNING_HIGH = 110
WATER_EMERGENCY = 110
WATER_MAX_VALID = 200

ADD_WATER_AT = 55
ADD_WATER_TO = 65
INITIAL_FILL_TO = 65

RANDOM_FILL_MIN = 55
RANDOM_FILL_MAX = 140
RANDOM_FILL_WEIGHTS = {
    'normal': 0.4,
    'warning': 0.3,
    'emergency': 0.2,
    'high_warning': 0.1,
}


def parse_water_data(raw_data) -> int:
    """
    解析WebSocket发来的JSON数据，提取液位值
    Java格式: [[液位,浊度,震动,湿度,倾斜,泵状态],[预测值]]
    """
    try:
        if isinstance(raw_data, bytes):
            raw_data = raw_data.decode('utf-8')
        raw_data = raw_data.strip()
        data = json.loads(raw_data)
        sensor_array = data[0]
        water_level = int(sensor_array[0])
        return water_level
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
        self.paused = False
        self.latest_water = None
        self.zone_samples = {
            '濒死': 0,
            '正常偏低': 0,
            '正常偏高': 0,
            '预警': 0,
            '应急': 0
        }

    def send_action(self, action: int):
        """通过HTTP GET控制闸门"""
        if action == self.last_action:
            return
        url = GATE_OPEN_URL if action == 1 else GATE_CLOSE_URL
        try:
            requests.get(url, timeout=2)
            self.last_action = action
        except Exception as e:
            print(f"\n[⚠️] 闸门控制失败: {e}")

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
        print(f"\r[帧{self.frame_count:6d}] 水位:{water:4d} {level} | 闸门:{act} | 样本:{len(self.training_data):6d} | {coverage}{extra}", end='', flush=True)

    def handle_add_water(self, current_water=None):
        self.send_action(0)
        self.current_action = 0
        self.last_action = -1  # 重置，确保加水后的第一次命令会发送
        self.paused = True
        target = random_fill_target()
        self.current_round += 1

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
            cmd = input("\n按 Enter 查看水位，输入 ok 继续训练: ").strip().lower()
            if cmd == 'ok':
                break
            if self.latest_water is not None:
                level_name = get_level_name(self.latest_water)
                diff = self.latest_water - target
                print(f"   📊 水位: {self.latest_water:4d} [{level_name}] | 距目标: {diff:+d}")
                if abs(diff) <= 5:
                    print(f"   ✅ 已达到目标水位")
                elif diff < 0:
                    print(f"   ⬆️  还需加水 {abs(diff)}")
                else:
                    print(f"   ⬇️  加多了 {diff}")
            else:
                print(f"   ❌ 暂无水位数据")

        print(f"\n[重新初始化] 清空历史缓冲区...")
        self.water_history.clear()
        self.action_history.clear()
        self.paused = False
        print(f"   ✅ 第{self.current_round}轮开始\n")

    async def run(self):
        print(f"\n{'='*60}")
        print(f"📊 数据采集器启动（WebSocket客户端 + HTTP版）")
        print(f"   连接地址: {WS_URL}")
        print(f"   闸门控制: HTTP GET")
        print(f"   采集时长: {COLLECT_SECONDS}秒 | 自动保存: 每{SAVE_INTERVAL}秒")
        print(f"   水位体系:")
        print(f"     死: 0-{WATER_DEAD} | 濒: {WATER_DEAD}-{WATER_CRITICAL}")
        print(f"     正常: {WATER_NORMAL_LOW}-{WATER_NORMAL_HIGH}")
        print(f"     预警: {WATER_WARNING}-{WATER_WARNING_HIGH}")
        print(f"     应急: {WATER_EMERGENCY}+ | 异常: >{WATER_MAX_VALID}")
        print(f"   随机加水范围: {RANDOM_FILL_MIN}-{RANDOM_FILL_MAX}")
        print(f"   区间权重: 正常40% | 预警30% | 应急20% | 正常偏高10%")
        print(f"{'='*60}\n")

        print(f"\n💧 请先加水至 {INITIAL_FILL_TO} 左右，按 Enter 开始...")
        input()

        self.last_save_time = time.time()
        start_time = time.time()

        while True:
            try:
                print(f"[⏳] 正在连接传感器 {WS_URL} ...")
                async with websockets.connect(WS_URL) as websocket:
                    print(f"[✅] 已连接！等待水位数据...\n")
                    print(f"⏳ 开始采集（实时显示，Ctrl+C 停止）...\n")

                    async for message in websocket:
                        self.frame_count += 1

                        water = parse_water_data(message)
                        if not is_valid_water(water):
                            self.abnormal_count += 1
                            continue

                        self.latest_water = water

                        if self.paused:
                            continue

                        # 检查是否需要加水
                        if water <= ADD_WATER_AT:
                            self.add_water_count += 1
                            self.handle_add_water(water)
                            continue

                        # 记录样本
                        self.record_sample(water)
                        self.update_history(water)

                        # 选择动作
                        self.choose_action()

                        # 定时保存
                        extra = ""
                        if time.time() - self.last_save_time >= SAVE_INTERVAL:
                            self.save_data()
                            extra = " | 💾已保存"

                        self.print_status(water, extra)

                        # 时间到了自动停止
                        if time.time() - start_time >= COLLECT_SECONDS:
                            print(f"\n\n⏰ 采集时长已到，正在停止...")
                            self.save_data()
                            self.send_action(0)
                            elapsed = time.time() - start_time
                            print(f"\n{'='*60}")
                            print(f"✅ 采集完成！")
                            print(f"   时长: {elapsed:.0f}秒 | 帧数: {self.frame_count}")
                            print(f"   样本: {len(self.training_data)} | 异常: {self.abnormal_count}")
                            print(f"   加水: {self.add_water_count}轮")
                            print(f"💾 最终保存至 {SAVE_FILE}")
                            print(f"{'='*60}")
                            return

            except websockets.exceptions.ConnectionClosed:
                print(f"\n[⚠️] WebSocket连接断开，5秒后重连...")
                await asyncio.sleep(5)
            except Exception as e:
                print(f"\n[⚠️] 连接异常: {e}，5秒后重连...")
                await asyncio.sleep(5)


if __name__ == '__main__':
    collector = DataCollector()
    try:
        asyncio.run(collector.run())
    except KeyboardInterrupt:
        print(f"\n\n⏹️ 用户中断")
        collector.save_data()
        collector.send_action(0)