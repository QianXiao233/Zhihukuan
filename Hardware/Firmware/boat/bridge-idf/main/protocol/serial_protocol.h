/**
 * 串口协议 —— 电脑 <-> 桥接板
 *
 * 帧格式（与 Software/boat-rescue-console/serial-service/index.js、arduino-reference/controller/controller.ino 完全一致）：
 *
 *   电脑 -> 桥接板 :  A5 5A | 26 字节 GroundToBoat | 1 字节累加校验   = 29 字节
 *   桥接板 -> 电脑 :  5A A5 | 32 字节 BoatToGround | 1 字节累加校验   = 35 字节
 *
 * 校验 = 载荷 26/32 字节逐字节相加取低 8 位。
 *
 * 结构体布局：
 *   GroundToBoat 两端都用 packed，固定 26 字节；
 *   BoatToGround 保持 ESP32 C 结构体自然对齐，固定 32 字节（内含填充）。
 *   下面用 _Static_assert 锁死，布局一改就编译失败——这是防止两端不一致的关键。
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SERIAL_BAUD_RATE          115200
#define CMD_HEADER_0              0xA5
#define CMD_HEADER_1              0x5A
#define STATUS_HEADER_0           0x5A
#define STATUS_HEADER_1           0xA5

/* 电脑命令超时：超过此时间未收到有效命令，则把待发命令归零（保持链路但不动船） */
#define HOST_COMMAND_TIMEOUT_MS   300

typedef struct __attribute__((packed)) {
    float   boat_x;
    float   boat_y;
    float   boat_heading;
    float   target_x;
    float   target_y;
    uint8_t mission_state;      /* 0=待命 1=自主航行 2=释放 3=返航 4=手动遥控 */
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

/** @brief 启动串口接收任务（解析电脑命令） */
void serial_protocol_start(void);

/** @brief 取当前待发往船端的命令（已应用超时归零逻辑），线程安全 */
void serial_protocol_get_command(ground_to_boat_t *out);

/** @brief 是否有过有效命令（用于屏幕显示"电脑在线"） */
bool serial_protocol_host_alive(void);

/** @brief 距离上次收到有效电脑命令的毫秒数 */
uint32_t serial_protocol_host_silence_ms(void);

/** @brief 已解析的有效命令计数（诊断用） */
uint32_t serial_protocol_command_count(void);

/** @brief 把船端状态按 35 字节帧写回电脑 */
void serial_protocol_send_status(const boat_to_ground_t *status);
