/**
 * ESP-NOW 链路协议 —— 船载主控 <-> 桥接板
 *
 * 结构体布局必须与下列两处逐字节一致，否则通信静默失败：
 *   - bridge-idf/main/protocol/serial_protocol.h  (ESP-IDF 桥接板)
 *   - Software/boat-rescue-console/serial-service/index.js + arduino-reference/controller/controller.ino (旧 Arduino 版)
 *
 * GroundToBoat : packed，固定 26 字节
 * BoatToGround : 保持 C 结构体自然对齐，固定 32 字节（内含填充）
 * 用 _Static_assert 锁死，布局一改立即编译失败。
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* mission_state 取值 */
#define MISSION_IDLE       0   /* 待命 */
#define MISSION_AUTONOMOUS 1   /* 自主航行 */
#define MISSION_RELEASE    2   /* 释放 */
#define MISSION_RETURN     3   /* 返航 */
#define MISSION_MANUAL     4   /* 手动遥控 */

typedef struct __attribute__((packed)) {
    float   boat_x;
    float   boat_y;
    float   boat_heading;
    float   target_x;
    float   target_y;
    uint8_t mission_state;
    uint8_t release_flag;
    int16_t manual_throttle;
    int16_t manual_steer;
} ground_to_boat_t;

typedef struct {
    float   boat_heading;
    int     left_motor_speed;
    int     right_motor_speed;
    uint8_t target_detected;
    int     local_target_x;
    int     local_target_y;
    float   estimated_dist_m;
    uint8_t emergency_mode;
} boat_to_ground_t;

_Static_assert(sizeof(ground_to_boat_t) == 26, "GroundToBoat 必须为 26 字节");
_Static_assert(sizeof(boat_to_ground_t) == 32, "BoatToGround 必须为 32 字节");
