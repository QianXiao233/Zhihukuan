/**
 * 诊断：芯片温度 + CPU 占用
 *
 * 目的：给"芯片发烫"提供可测量的依据，而不是靠推断。
 *
 *   温度：ESP32-S3 内置温度传感器读的是**芯片结温**，通常比环境温度高
 *         10~25 °C。持续射频发射（WiFi/ESP-NOW）时结温 50~60 °C 属正常；
 *         若长期 70 °C 以上就要查原因。
 *
 *   CPU：调用率反映软件是否有空转。若空闲率很低（占用很接近 100%），
 *        说明有任务在忙等/死循环，那会实实在在地加热芯片；
 *        若空闲率很高而温度仍高，则主因更可能在射频或硬件供电上。
 *
 * 需要 sdkconfig 打开 CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS。
 * 未打开时本模块会打印一条提示并跳过 CPU 统计（不影响固件运行）。
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/** @brief 初始化温度传感器（失败不致命，仅打印告警） */
void diag_init(void);

/** @brief 周期调用；内部按 5 秒节流输出一次温度与 CPU 占用 */
void diag_tick(void);

/** @brief 读取芯片结温（°C）；传感器不可用时返回 false */
bool diag_get_temperature(float *out_celsius);

/**
 * @brief 读取 CPU 占用百分比
 * @return false 表示未开启运行时间统计，数据不可用
 */
bool diag_get_cpu_load(uint32_t *out_cpu0, uint32_t *out_cpu1);
