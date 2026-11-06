# 决策大脑（inference）

智慧大坝 AI 决策内核。从桌面「智慧大坝」原型迁移而来，**直接通过 MQTT 控制现场闸门，不经过 Java 后端**。

## 架构

```
固件 STM32F407
   │  rtu/status（每 1.5s 上报水位 + 8 路继电器状态）
   ▼
MQTT broker ──► inference 服务（本目录）
   ▲                  │
   │  rtu/control     │  LSTM 世界模型 → MPC 选档位 → 4 门协调
   └──────────────────┘
                      ├──► 直连网关（HTTP :5001）：实时状态 → 防汛调度页
                      └──► 服务接入总线：待确认开闸请求 → 全局弹窗
```

**没有 Java 中转。** 闸门控制走 MQTT，Python 服务是唯一的决策与控制出口。

### 两类数据走两条通道（重要）

| 数据 | 通道 | 原因 |
|---|---|---|
| 水位、闸门、最近决策 | **直连 HTTP :5001** | 高频快照。走消息队列只会引入延迟与堆积 |
| 待确认开闸请求 | **服务接入总线** `brain.pending` | 这是"需要人处理的任务"，要落库、要有投递保证、要能审计 |

开闸确认弹窗因此挂在**前端根节点**（`GlobalApprovalModal`），
运维停在哪一页都能收到——不能因为"正好不在防汛页"而错过开闸请求。

### 总线接入

待确认请求通过后端「服务接入」总线投递，需要先在平台
**服务接入** 页创建客户端（允许发布 `brain.#`），然后配置：

```bash
export BUS_BASE_URL=http://127.0.0.1:8085
export BUS_CLIENT_ID=dam-brain
export BUS_CLIENT_SECRET=<创建时返回的密钥，只显示一次>
```

客户端认证格式由后端 `BusController.requireClient` 决定：
`Authorization: Bearer <clientId>.<secret>`。

未配置总线的行为：**安静降级**。决策照常运行，只是待确认请求不会推送到前端，
日志里会有「总线未配置，待确认请求不会上报」。总线不可达同理——
它是旁路通知，绝不能影响决策主循环。

#### 幂等（为什么确认要带 requestId）

总线是 **at-least-once**：同一条待确认请求可能被投递多次。若不做校验，
已经处理过的请求可能在无人知情时**再开一次闸**——这在物理控制里是事故。
所以每个待确认请求带一个 `requestId`，带过期 id 的确认会被拒绝并返回当前有效的 id。

## 它做什么

1. **世界模型**（LSTM）—— 学习「水位 + 闸门动作 → 下一时刻水位」；
2. **MPC 规划** —— 生成数十个候选档位序列，各推演 10 步，按代价函数选最优；
3. **四门协调** —— 把「需要几档放水能力」落到具体开哪几个门，兼顾磨损均衡；
4. **在线学习** —— 边跑边用经验回放微调，误差大就学得勤、误差小就放缓；
5. **人工确认** —— 建议开闸时挂起等确认，含拒绝冷却与开闸保持。

## 4 个闸门怎么协调

现场有 4 个**并联**闸门（固件 `devices.c`：继电器 1~4 = 闸门一~四），开得越多放水越快，
可组合出 0~4 共 5 档放水能力。

### 档位映射规则

| 优先级 | 规则 | 目的 |
|---|---|---|
| 1 | 可用性优先 | 故障/检修的门直接排除，绝不参与 |
| 2 | 精确分档 | 需要 N 档就恰好开 N 个门，不多开 |
| 3 | 最小切换 | 已开的门尽量不动，减少启停 |
| 4 | 磨损均衡 | 优先选累计运行时长最短的门 |

优先级顺序很重要：**宁可多换一次门，也不能少开一个门导致放水不足。**

典型行为：

```
需要开 2 个门  → 开 #1、#2
降到 1 个门    → 关掉运行时长较短的 #2，保留 #1（不是简单关最大编号）
升到 4 个门    → 补开 #3、#4，已开的 #1、#2 不动
档位不变       → 返回空方案，不发任何 MQTT 指令
```

### 磨损均衡怎么算

每个门累计运行秒数与启停次数，长期运行后各门会自然趋于均衡。
换新闸门后可调用 `reset_counters()` 清零。

### 世界模型的档位适配（重要局限）

模型是在**单门 0/1** 上训练的，动作输入只有两个取值。直接把 0~4 喂进去，
输入会落在训练分布之外，输出无意义。

`predict_future_scaled()` 的做法是：

```
1. 先算「单门全开」和「单门全关」两条基准轨迹
2. 净变化 = 开闸轨迹 - 关闸轨迹
3. N 门时 ≈ 关闸轨迹 + N × 净变化
```

**这个线性近似的成立条件**：多门放的是同一水体、出水口互不干扰、总流量未超出
模型见过的量级。4 门全开时误差会放大——水位下降速率不可能随门数无限线性增长，
最终受来水量限制。

代码里对倍率做了上限截断，**宁可低估放水能力，也不给出过于乐观的预测**导致决策激进。

> 如果要更准，需要按「N 门同时开」重新采集一轮数据并训练多值动作空间。
> 现有 683 条样本全是单门场景，做不到。

## 与原型的关键差异

| 方面 | 原型（智慧大坝） | 本服务 |
|---|---|---|
| 数据源 | WebSocket `ws://192.168.10.251:8085` 或裸 TCP 帧 `AA11…DBBB` | **MQTT** `rtu/status` |
| 闸门控制 | HTTP `GET /RelayControl/Open` | **MQTT** `rtu/control`，固件已支持 |
| 闸门数量 | 单门 | **4 门并联，分档 + 轮换** |
| 水位单位 | 原始刻度 50~140 | **米** 0.20~1.20 |
| 对外接口 | Flask :5001 | **FastAPI** :5001 |
| 训练脚本 | 有语法错误，无法运行 | 已修复可用 |
| 状态管理 | 散落的 8 个布尔字段 | 显式状态机 + 锁 |

### 单位换算是必须注意的一点

模型在原始刻度上训练（`water_mean≈72.2`、`water_std≈15.95`），平台水位以米计。
直接喂米制读数会落在训练分布之外，**不会报错**，只会给出离谱的数字。

`WaterScale` 在模型边界统一换算（默认 `米 × 100`），0.20~1.20 m 正好映射到 20~120。
现场换量程改 `WATER_SCALE_FACTOR` 即可，不必重新训练。

## 快速开始

```bash
cd Software/reservoir-platform/inference

# 1. 安装依赖（先装 PyTorch，见 requirements.txt 注释）
pip install -r requirements.txt

# 2. 启动（默认只观察，不下发闸门指令）
python -m uvicorn server:app --host 0.0.0.0 --port 5001
```

打开 `http://127.0.0.1:5001/docs` 看交互式接口文档。

## 安全默认值（重要）

初次接入时 `DISPATCH_CONTROL` 默认 **false**，服务只做决策展示，不动闸门：

```bash
# 确认决策合理后再打开
export DISPATCH_CONTROL=true
```

## 配置项

| 变量 | 默认 | 说明 |
|---|---|---|
| `MODEL_PATH` | `models/world_model.pt` | 模型检查点 |
| `GATE_COUNT` | `4` | **参与协调的闸门数** |
| `GATE_RELAY` | `1` | 单门操作时的默认继电器 |
| `MQTT_ENABLED` | `true` | 是否订阅 MQTT |
| `MQTT_BROKER` | `tcp://127.0.0.1:1883` | broker 地址 |
| `MQTT_TOPIC` | `rtu/status` | 上行水位主题 |
| `MQTT_CONTROL_TOPIC` | `rtu/control` | 下行控制主题 |
| `AUTO_DECIDE` | `true` | 启动后自动订阅并决策 |
| `DISPATCH_CONTROL` | `false` | 是否真正下发控制指令 |
| `WATER_SCALE_FACTOR` | `100` | 米 → 模型刻度 |
| `API_TOKEN` | 空 | 共享密钥（前端 `VITE_BRAIN_TOKEN` 对应） |
| `STATION_NAME` | `水库监测站` | 站点名，出现在总线待确认事件里 |
| `BUS_BASE_URL` | 空 | 总线地址（如 `http://127.0.0.1:8085`） |
| `BUS_CLIENT_ID` | 空 | 服务接入客户端 id |
| `BUS_CLIENT_SECRET` | 空 | 客户端密钥（只在创建时显示一次） |
| `PORT` | `5001` | 服务端口 |

## 接口

| 路径 | 方法 | 说明 |
|---|---|---|
| `/health` | GET | 健康检查（不鉴权） |
| `/api/brain/status` | GET | 完整状态：水位、闸门阵列、学习、模型 |
| `/api/brain/decide` | POST | 手动喂一帧水位（调试/回放） |
| `/api/brain/confirm` | POST | 确认开闸，可带 `{"level": N}` 调整档位 |
| `/api/brain/reject` | POST | 拒绝开闸，进冷却 |
| `/api/brain/reset` | POST | 复位（默认保留冷却） |
| `/api/brain/control` | POST | 人工控制：`{"state":0}` 全关 / `{"state":N}` 开 N 门 / `{"relay":3,"state":0}` 单路 |

### 确认时可调整档位

AI 建议开 3 个门，但现场判断只开 1 个就够——`POST /api/brain/confirm {"level": 1}`
即可降档。强制只能"全盘接受"会让人干脆点拒绝，反而更不安全。

## 工具

```bash
# 采集训练数据（走 MQTT，默认 dry-run 不下发指令）
python tools/collect_data.py --seconds 600 --out data/training_data.npy

# 重新训练世界模型
python tools/train_model.py --data data/training_data.npy --out models/world_model.pt
```

## 测试

```bash
# 单元测试
python -m unittest discover -s tests

# 端到端：本地 broker + 模拟固件，验证四门真实下发
pip install amqtt
python tests/e2e_mqtt.py
```

端到端会验证：水位上报、决策产生、应急下建议全开 4 门、
**待确认期间闸门保持全关**、确认后继电器 1~4 逐个吸合。

## 目录

```
inference/
├── brain/
│   ├── world_model.py   LSTM 网络 + 单位换算 + 多档位推演
│   ├── planner.py       MPC 候选生成（档位空间）、代价函数
│   ├── gates.py         四门协调：分档 + 磨损均衡 + 最小切换
│   ├── learner.py       经验回放、难例采样、自适应学习间隔
│   ├── gate.py          开闸确认与冷却状态机
│   └── engine.py        串起以上模块的决策内核
├── server.py            FastAPI 服务
├── mqtt_client.py       MQTT 收发（含固件报文解析、多路下发）
├── bus_client.py        服务接入总线客户端（上报待确认请求）
├── config.py            环境变量配置
├── models/world_model.pt
├── tools/
│   ├── train_model.py   训练脚本（已修复原版语法错误）
│   ├── collect_data.py  数据采集（MQTT）
│   └── demo_feed.py     本地演示：模拟 broker + 固件（含 ws 监听）
└── tests/
    ├── test_brain.py    单位换算、代价函数、单门状态机
    ├── test_gates.py    四门协调、磨损均衡、故障隔离
    ├── test_bus.py      总线降级、确认幂等
    └── e2e_mqtt.py      端到端验收
```

## 本地演示（无硬件）

没有真实大坝时，用内置的模拟数据源跑起来看：

```bash
# 终端 1：模拟 broker（TCP 1883 + WebSocket 8083）+ 大坝固件
python tools/demo_feed.py --port 1883 --interval 1.5 --start-level 1.20

# 终端 2：决策服务
MQTT_ENABLED=true DISPATCH_CONTROL=true GATE_COUNT=4 \
  python -m uvicorn server:app --host 0.0.0.0 --port 5001
```

模拟器包含一个简单的水池模型：闸门开得越多水位下降越快，全关则缓慢上涨。
`--start-level 1.20` 直接落在应急区，能立刻看到「建议开 4 门，等待确认」。

水位会随开闸真实变化，因此在页面上点开关能看到完整闭环，
而不是看一组静止的数字。

## 故障排查

**服务起来了但闸门不动** —— 检查 `DISPATCH_CONTROL=true`；看 `/api/brain/status`
的 `mqtt.connected` 与 `mqtt.lastError`；确认 `GATE_COUNT` 与现场实际门数一致。

**某个门一直不动** —— 可能被标记为不可用（`gates` 里 `available: false`）。
用 `/api/brain/control {"relay":N,"state":1}` 单独测试该路。

**水位一直预热中** —— 需攒满 10 帧历史（1.5 秒/帧 ≈ 15 秒），第 11 帧起才决策。

**预测值明显离谱** —— 检查 `WATER_SCALE_FACTOR`。单位换算错了不会报错。
