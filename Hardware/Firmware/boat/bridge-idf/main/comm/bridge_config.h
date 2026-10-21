/**
 * 桥接板固件 —— 硬件地址配置
 *
 * 真值来源：Arduino 工程里的 arduino-reference/boat_config.h（两个 Arduino 固件共用）。
 * 本文件通过相对路径 #include 它，因此**只有一份定义**，不存在改一处漏一处。
 *
 * 目录关系：
 *     Zhihukuan/Hardware/Firmware/boat/arduino-reference/boat_config.h          <- 真值（船端 + 桥接板 Arduino 版）
 *     Zhihukuan/Hardware/Firmware/boat/bridge-idf/main/comm/本文件    <- ESP-IDF 桥接板固件引用它
 *
 * 若日后把 bridge-idf 移出 boat 目录，此相对路径会失效，需要同步调整；
 * 那种情况下建议把 MAC 复制过来并注明“与 arduino-reference/boat_config.h 保持一致”。
 */
#pragma once

#include "../../../arduino-reference/boat_config.h"
