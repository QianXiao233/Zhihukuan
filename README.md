# 智护库安项目结构

代码已按软件与硬件两大类整理；软件再按产品和职责拆分，硬件侧的固件工程保留原有编译目录结构。

```text
Zhihukuan/
├── Software/
│   ├── reservoir-platform/
│   │   ├── frontend/            # Vue 水库数字人和管理界面；src 内按页面、组件、语音、API 分类
│   │   ├── backend/             # Spring Boot API、鉴权、设备/参数管理、MQTT、数据库
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
- 水库前端：在 `Software/reservoir-platform/frontend/` 执行 `npm run dev` 或 `npm run build`。
- 水库后端：在 `Software/reservoir-platform/backend/` 使用 `mvnw.cmd test`。
- 本地语音识别：安装 `Software/reservoir-platform/speech-recognition/requirements.txt` 后，进入该目录运行 `python asr_server.py`。
- ESP-IDF 船端固件：分别进入 `Hardware/Firmware/boat/bridge-idf/` 或 `Hardware/Firmware/boat/controller-idf/`，使用各自的 `idf-env.ps1` 和 ESP-IDF 工具链。
- STM32F407 固件：工程入口为 `Hardware/Firmware/daba/CMakeLists.txt`，芯片配置见 `Hardware/Firmware/daba/daba.ioc`。

旧版无人艇项目文档备份保存在 `Software/boat-rescue-console/docs/archive/`；当前总览文档位于 `Software/boat-rescue-console/docs/Project.md`。
