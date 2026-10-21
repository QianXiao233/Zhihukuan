#ifndef __DEVICES_H
#define __DEVICES_H

#include "main.h"

/* =====================================================================
 * 设备层：继电器 / 传感器的统一结构化管理
 *
 * 继电器和传感器的硬件映射、运行状态都集中在这两张表里，
 * 增删设备只需改 devices.c 中的表项，无需改动各任务代码。
 * ===================================================================== */

/* ============================ 继电器 ============================ */
#define RELAY_COUNT  8   /* 闸门继电器总数 */

typedef struct {
    GPIO_TypeDef *port;   /* GPIO 端口 */
    uint16_t      pin;    /* GPIO 引脚 */
    uint8_t       state;  /* 0=OFF, 1=ON */
} Relay_Channel_t;

extern Relay_Channel_t g_relays[RELAY_COUNT];

/* 初始化全部继电器引脚（推挽输出，上电默认关闭） */
void Relay_InitAll(void);

/* 设置继电器状态（id: 1~RELAY_COUNT, state: 0/1），低电平有效 */
void Relay_SetState(uint8_t id, uint8_t state);

/* 读取继电器状态（id: 1~RELAY_COUNT） */
uint8_t Relay_GetState(uint8_t id);
uint32_t Relay_GetStateMask(void);
void Relay_SetStateMask(uint32_t mask);

/* ============================ 传感器 ============================ */
#define SENSOR_COUNT  4   /* Modbus 传感器总数 */

typedef enum {
    SENSOR_LEVEL = 0,   /* 液位 */
    SENSOR_TEMP,        /* 温度 */
    SENSOR_PH,          /* pH */
    SENSOR_ORP,         /* ORP */
} SensorId_t;

/* 原始值 → 工程量的缩放方式 */
typedef enum {
    SCALE_LEVEL,        /* raw / 9.8        → cm */
    SCALE_TEMP,         /* raw * 0.1        → °C */
    SCALE_PH,           /* raw * 0.01       → pH */
    SCALE_ORP,          /* (int16)raw       → mV */
} SensorScale_t;

typedef struct {
    uint8_t       slave;        /* Modbus 从机地址 */
    uint16_t      reg;          /* 保持寄存器地址 */
    SensorScale_t scale;        /* 缩放方式 */
    float         value;        /* 缩放后的工程量 */
    uint8_t       valid;        /* 数据有效标志 */
    uint8_t       fail;         /* 连续失败计数 */
    uint8_t       fail_thresh;  /* 失败阈值（连续失败超此值置 invalid） */
} Sensor_Channel_t;

extern Sensor_Channel_t g_sensors[SENSOR_COUNT];

/* 连续失败阈值（防抖：连续 N 次读不到才认为传感器断开） */
#define SENSOR_FAIL_THRESH   3

/* 轮询全部传感器：读取 → 缩放 → 防抖更新 valid */
void Sensors_Poll(void);

#endif /* __DEVICES_H */
