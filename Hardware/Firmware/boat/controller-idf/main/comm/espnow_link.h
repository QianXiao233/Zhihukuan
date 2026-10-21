/**
 * ESP-NOW 链路 —— 船载主控侧
 *
 * 对端 MAC / 信道取自 arduino-reference/boat_config.h（与桥接板共用一份定义）。
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "link_protocol.h"

/** @brief 初始化 Wi-Fi STA + ESP-NOW，把桥接板加为 peer */
void espnow_link_start(void);

/**
 * @brief 取最近一次收到的命令
 * @return true 表示拿到新命令（自上次调用后有过新帧）
 */
bool espnow_link_take_command(ground_to_boat_t *out);

/** @brief 距上次收到命令的毫秒数（UINT32_MAX = 从未收到） */
uint32_t espnow_link_silence_ms(void);

/** @brief 是否已收到过至少一帧（判断桥接板是否曾经在线） */
bool espnow_link_ever_seen(void);

/** @brief 发送状态帧给桥接板（20 Hz 调用，内部做限频） */
void espnow_link_send_status(const boat_to_ground_t *status);

/** @brief 本板 ESP-NOW MAC 字符串 */
const char *espnow_link_own_mac_str(void);

/** @brief 桥接板 MAC 字符串 */
const char *espnow_link_bridge_mac_str(void);

/** @brief 接收帧计数与发送失败计数（调试用） */
void espnow_link_counters(uint32_t *recv, uint32_t *send_fail);
