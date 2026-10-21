/**
 * ESP-NOW 桥接层 —— 与船载 DFR1063 通信
 *
 * 对端 MAC / 信道全部来自 arduino-reference/boat_config.h，两个固件共用一处定义，
 * 避免"改一处漏一处导致链路不通"。
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "serial_protocol.h"   /* boat_to_ground_t */

/** @brief 初始化 Wi-Fi STA + ESP-NOW，并把船载主控加为 peer */
void espnow_bridge_start(void);

/** @brief 把电脑命令发给船端（20 Hz 调用），内部做限频 */
void espnow_bridge_send_command(const ground_to_boat_t *command);

/** @brief 取最近一次收到的船端状态快照；返回 false 表示从未收到 */
bool espnow_bridge_get_status(boat_to_ground_t *out);

/** @brief 距离上次收到船端状态的毫秒数（UINT32_MAX = 从未收到） */
uint32_t espnow_bridge_boat_silence_ms(void);

/** @brief 最近一次发送是否成功（来自发送回调） */
bool espnow_bridge_last_send_ok(void);

/** @brief 已发送帧数与已接收帧数 */
void espnow_bridge_counters(uint32_t *sent, uint32_t *received, uint32_t *send_fail);

/** @brief 桥接板自身的 ESP-NOW MAC 字符串（如 "A0:F2:62:E3:94:DC"） */
const char *espnow_bridge_own_mac_str(void);

/** @brief 船端 MAC 字符串 */
const char *espnow_bridge_peer_mac_str(void);
