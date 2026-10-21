/**
 * 载荷释放机构 —— MG90S 舵机（180° 金属齿轮）
 *
 * 硬件：3D 打印插销 + 复位弹簧，断电自动锁死。
 * 信号：GPIO6，50 Hz PWM，脉宽 500-2500 us 对应 0-180°。
 *
 * 重要：原 Arduino 版 main.ino 的 releasePayload() 里舵机代码是被注释掉的，
 * 且 Servo 对象从未创建，所以"投放"这一环实际没有实现。这里补齐。
 *
 * 实现方式：非阻塞状态机。
 *   舵机拉动插销需要保持约 500 ms，如果用 delay() 会阻塞主循环，
 *   导致这段时间收不到 ESP-NOW 命令、看门狗也可能报警。
 *   因此这里用 tick 计时推进，由 control_loop 周期调用 servo_release_tick()。
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/** @brief 初始化舵机 PWM（上电时回到锁定位置） */
void servo_release_init(void);

/**
 * @brief 触发释放（只触发一次，重复调用在动作期间会被忽略）
 * @return true 表示本次调用启动了释放动作
 */
bool servo_release_trigger(void);

/** @brief 周期推进释放状态机，需在主循环中调用 */
void servo_release_tick(void);

/** @brief 释放动作是否正在进行 */
bool servo_release_busy(void);

/** @brief 已完成的释放次数（诊断用） */
uint32_t servo_release_count(void);
