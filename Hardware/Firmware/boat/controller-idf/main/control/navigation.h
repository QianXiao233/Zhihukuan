/**
 * 航行控制 —— 三种自主行为
 *
 * 1) 坐标导航：电脑下发 (boat_x,boat_y)->(target_x,target_y) 做航向 PID 差速控制，
 *    进入目标 40 cm 内切换到 HUSKYLENS 视觉精细靠近，视觉距离 <= 20 cm 停车。
 *    **依赖电脑持续提供全局定位（UVC 相机）**。
 *
 * 2) 二哈自主搜救（vision-only）：完全不需要电脑定位。
 *    没看到目标 -> 原地旋转搜索；看到目标 -> 转向并前进接近；
 *    估算距离 <= 20 cm 停车。这是"识别到就自主前往"的行为。
 *
 * 3) 应急巡航：通信超时（桥接板失联）后自动进入，行为与 2) 相同。
 */
#pragma once

#include <stdbool.h>

#include "link_protocol.h"

void navigation_reset(void);

/**
 * @brief 判断电脑下发的坐标是否可用（决定 mission_state=1 走哪种自主行为）
 *
 * 判据：坐标为有限数、且不是全 0（全 0 视为"未填写"）、且在合理量程内。
 * 电脑未提供定位时应返回 false，此时走二哈自主搜救。
 */
bool navigation_data_valid(const ground_to_boat_t *cmd);

/**
 * @brief 坐标导航（mission_state = 1 且坐标有效时使用）
 */
void navigation_autonomous(const ground_to_boat_t *cmd,
                           float vision_dist,
                           bool target_seen,
                           int target_x_px);

/**
 * @brief 二哈自主搜救（mission_state = 1 且坐标无效时使用）
 *
 * 只看二哈：无目标则原地旋转搜索，有目标则接近，距离达标停车。
 * 与原应急行为共用同一套控制律。
 */
void navigation_vision_search(float vision_dist, bool target_seen, int target_x_px);

/**
 * @brief 应急巡航（通信超时后调用）—— 与 navigation_vision_search 行为一致，
 *        单独保留以便状态显示区分"应急"与"自主搜救"。
 */
void navigation_emergency(float vision_dist, bool target_seen, int target_x_px);

/** @brief 是否已切换到末端视觉靠近阶段（调试显示用） */
bool navigation_visual_approach_active(void);
