# 智护库安项目结构

代码已按软件与硬件两大类整理；软件再按产品和职责拆分，硬件侧的固件工程保留原有编译目录结构。

```text
Zhihukuan/
├── Software/
│   ├── reservoir-platform/
│   │   ├── frontend/            # Vue 水库数字人和管理界面；src 内按页面、组件、语音、API 分类
│   │   ├── backend/             # Spring Boot API、鉴权、设备/参数管理、MQTT、数据库
│   │   ├── inference/           # AI 闸门决策服务：LSTM 世界模型 + MPC 规划 + 在线学习
│   │   └── speech-recognition/  # FunASR 本地语音识别服务
│   └── boat-rescue-console/
│       ├── dashboard/           # React 无人艇网页驾驶台
│       ├── serial-service/      # Node.js 串口、WebSocket、船端协议与协议测试
│       ├── vision/              # Python 水池标定、ArUco 船定位、目标检测
│       ├── tools/               # 串口诊断工具
│       └── docs/                # 无人艇架构和操作文档
└── Hardware/
    └── Firmware/
        ├── boat/
        │   ├── bridge-idf/      # ESP32-S3 桥接板：USB 串口、ESP-NOW、LCD 状态屏
        │   ├── controller-idf/  # ESP32-C3 船载主控：电机、舵机、二哈视觉、导航
        │   └── arduino-reference/ # Arduino 参考固件和共用硬件地址配置
        └── daba/                # STM32F407 固件：传感、Modbus、TCP、LCD 等模块
```

## 常用入口

- 无人艇控制台：在 `Software/boat-rescue-console/` 执行 `npm run dev`；构建和协议验证分别执行 `npm run build`、`npm run test:protocol`。
- 无人艇视觉定位：依照 `Software/boat-rescue-console/vision/requirements.txt` 安装依赖，并按 `Software/boat-rescue-console/docs/Project.md` 的步骤运行。
  - 目标识别：`detector.py`（多段 HSV + 水池 ROI + 形状打分 + 时序跟踪，可选 `models/yolov8n.onnx` 人形检测），回归测试 `python test_detector.py`；
  - 自主规划：`planner.py`（A* + 覆盖搜索 + 纯追踪虚拟目标），回归测试 `python test_planner.py`；
  - 航向算法：回归测试 `python test_boat_heading.py`；
  - 以上测试都不需要相机，直接 `cd Software/boat-rescue-console/vision && python <test>.py`。
- 电脑端顶视落水识别（只用电脑 + 顶部俯拍摄像头）：见 `Software/boat-rescue-console/docs/PC_TOPVIEW_MODEL.md`（标注/训练/接入一条龙，产物只要 ONNX）。
- 二哈自定义模型（识别模拟溺水人员）：训练/打包/部署全流程见 `Software/boat-rescue-console/docs/HUSKYLENS_CUSTOM_MODEL.md`，训练工具在 `Software/boat-rescue-console/vision/training/`；固件侧只需把 `HUSKY_ALGORITHM_ID` 改成设备上显示的算法 ID。
- 水库前端：在 `Software/reservoir-platform/frontend/` 执行 `npm run dev` 或 `npm run build`；`/boat` 页是平台原生的 Vue 驾驶台（`views/BoatView.vue`），`Software/boat-rescue-console` 的 React 控制台保留为独立调试工具。
- 部署：前端/后端上线步骤见 `Software/reservoir-platform/deploy/README.md`（站点根为 `/www/wwwroot/zhka/h5/reservoir-platform`）。
- 水库后端：在 `Software/reservoir-platform/backend/` 使用 `mvnw.cmd test`。
- AI 闸门决策：在 `Software/reservoir-platform/inference/` 安装 `requirements.txt` 后运行 `python -m uvicorn server:app --port 5001`；说明见该目录 `README.md`。
  - 该服务**直接通过 MQTT 控制 4 个并联闸门**（`rtu/status` 上报、`rtu/control` 下发），不经过 Java 后端；
  - 决策按档位输出 0~4（开几个门），由协调器分配到具体闸门并轮换均衡磨损；
  - `DISPATCH_CONTROL` 默认 `false`（只观察不动作），确认决策合理后再打开；
  - 单元测试 `python -m unittest discover -s tests`；端到端验收 `python tests/e2e_mqtt.py`（需 `pip install amqtt`）。
- 本地语音识别：安装 `Software/reservoir-platform/speech-recognition/requirements.txt` 后，进入该目录运行 `python asr_server.py`。
- ESP-IDF 船端固件：分别进入 `Hardware/Firmware/boat/bridge-idf/` 或 `Hardware/Firmware/boat/controller-idf/`，使用各自的 `idf-env.ps1` 和 ESP-IDF 工具链。
- STM32F407 固件：工程入口为 `Hardware/Firmware/daba/CMakeLists.txt`，芯片配置见 `Hardware/Firmware/daba/daba.ioc`。

旧版无人艇项目文档备份保存在 `Software/boat-rescue-console/docs/archive/`；当前总览文档位于 `Software/boat-rescue-console/docs/Project.md`。
