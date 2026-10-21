/**
 * 船载主控固件 —— 硬件地址配置转发
 *
 * 真值来源：Arduino 工程里的 arduino-reference/boat_config.h（三个固件共用一份：
 * 桥接板 Arduino 版、桥接板 ESP-IDF 版、船载主控 ESP-IDF 版）。
 * 本文件只做 include 转发，保证"只有一份定义"，不存在改一处漏一处。
 */
#pragma once

/* 目录关系： main/shared/ -> main/ -> controller-idf/ -> boat/ -> arduino-reference/ */
#include "../../../arduino-reference/boat_config.h"

/* ---------------------------------------------------------------------------
 * 安全开关：电机输出
 *   1 = 正常输出（与 Arduino 版默认一致）
 *   0 = 电机强制不转，用于陆地调试
 *
 * 陆地调试建议改成 0 重新编译 —— 比拔线更可靠，因为固件层就断掉了输出，
 * 即使误发指令也不会转。
 * ------------------------------------------------------------------------- */
#define ENABLE_MOTOR_OUTPUT   1

/* ---------------------------------------------------------------------------
 * HUSKYLENS 2 通信方式：0 = I2C（与现有接线一致），1 = UART
 *
 * 默认 I2C：DFR1063 的 GPIO8=SDA / GPIO9=SCL，二哈的绿线接 SDA、蓝线接 SCL，
 * 且二哈的"Protocol Type"需设为 I2C。保持与原来 Arduino 版一致，不用改接线。
 * ------------------------------------------------------------------------- */
#define HUSKYLENS_USE_UART   0

/* I2C 引脚与速率 */
#define HUSKY_I2C_SDA_GPIO   8
#define HUSKY_I2C_SCL_GPIO   9
#define HUSKY_I2C_FREQ_HZ    100000
#define HUSKY_I2C_ADDR       0x50

/* UART 备用引脚（仅当 HUSKYLENS_USE_UART=1 时生效） */
#define HUSKY_UART_PORT      1
#define HUSKY_UART_TX_GPIO   1
#define HUSKY_UART_RX_GPIO   2
#define HUSKY_UART_BAUD      115200
