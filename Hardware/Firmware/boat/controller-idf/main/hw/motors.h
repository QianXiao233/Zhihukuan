/**
 * 双电机驱动（差速推进）
 *
 * 每路电机用「PWM + 方向」两个引脚：
 *   M1: PWM=GPIO0   DIR=GPIO1
 *   M2: PWM=GPIO2   DIR=GPIO10
 *
 * 与 Arduino 版行为一致：PWM 取绝对值，方向由正负号决定。
 * 安全开关 ENABLE_MOTOR_OUTPUT 在编译期可通过 CMake 定义覆盖，
 * 默认沿用原固件的"启用"，但陆地调试建议先架空。
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/** @brief PWM 上限（与 Arduino 版 constrain 到 200 保持一致） */
#define MOTOR_PWM_MAX 200

void motors_init(void);

/**
 * @brief 设置两侧电机
 * @param left   -200..200，负值反转
 * @param right  -200..200，负值反转
 */
void motors_set(int left, int right);

/** @brief 立即停转 */
void motors_stop(void);

/** @brief 取当前实际下发的 PWM 值（供状态上报） */
void motors_get(int *left, int *right);
