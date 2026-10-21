# 硬件与固件

本目录集中放置设备侧工程；`Firmware/` 下按设备/子系统分开：

- `Firmware/boat/bridge-idf/`：ESP32-S3 桥接板，负责电脑 USB 串口与船端 ESP-NOW 之间的数据转发，并驱动状态屏。
- `Firmware/boat/controller-idf/`：ESP32-C3 船载主控，按通信、导航、传感器和执行器拆分代码。
- `Firmware/boat/arduino-reference/`：Arduino 旧版参考实现；`boat_config.h` 保存共享 MAC 和信道配置，ESP-IDF 工程通过相对包含引用。
- `Firmware/daba/`：STM32F407 工程；`Core/` 是应用与板级初始化，`Drivers/` 是芯片驱动，`LWIP/` 与 `Middlewares/` 是网络与 RTOS 中间件。

无人艇整机架构、接线、运行和固件烧录说明见 [`Software/boat-rescue-console/docs/Project.md`](../Software/boat-rescue-console/docs/Project.md)。
