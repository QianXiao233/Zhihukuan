#include "devices.h"
#include "modbus.h"
#include "rtc_config.h"
#include "delay.h"

/* ============================ 继电器 ============================
 * 低电平有效：GPIO_PIN_RESET = 吸合(ON)，GPIO_PIN_SET = 断开(OFF)
 * 引脚宏引用 main.h 中的硬件定义（单一来源），上电默认全部关闭
 */
Relay_Channel_t g_relays[RELAY_COUNT] = {
    { Relay1_GPIO_Port, Relay1_Pin, 0 },   /* 闸门一 */
    { Relay2_GPIO_Port, Relay2_Pin, 0 },   /* 闸门二 */
    { Relay3_GPIO_Port, Relay3_Pin, 0 },   /* 闸门三 */
    { Relay4_GPIO_Port, Relay4_Pin, 0 },   /* 闸门四 */
    { Relay5_GPIO_Port, Relay5_Pin, 0 },   /* 闸门五 */
    { Relay6_GPIO_Port, Relay6_Pin, 0 },   /* 闸门六 */
    { Relay7_GPIO_Port, Relay7_Pin, 0 },   /* 闸门七 */
    { Relay8_GPIO_Port, Relay8_Pin, 0 },   /* 闸门八 */
};

void Relay_InitAll(void)
{
    GPIO_InitTypeDef g = {0};

    /* 自包含时钟使能：不依赖 CubeMX 生成代码的调用位置 */
    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();

    g.Mode  = GPIO_MODE_OUTPUT_PP;
    g.Pull  = GPIO_NOPULL;
    g.Speed = GPIO_SPEED_FREQ_LOW;

    for (int i = 0; i < RELAY_COUNT; i++) {
        /* 初始电平按表内 state 设定：1=吸合(RESET)，0=断开(SET) */
        HAL_GPIO_WritePin(g_relays[i].port, g_relays[i].pin,
                          g_relays[i].state ? GPIO_PIN_RESET : GPIO_PIN_SET);
        g.Pin = g_relays[i].pin;
        HAL_GPIO_Init(g_relays[i].port, &g);
    }
}

void Relay_SetState(uint8_t id, uint8_t state)
{
    if (id < 1 || id > RELAY_COUNT) return;

    g_relays[id - 1].state = state ? 1 : 0;
    /* 低电平有效：state=1(ON) → RESET，state=0(OFF) → SET */
    HAL_GPIO_WritePin(g_relays[id - 1].port, g_relays[id - 1].pin,
                      state ? GPIO_PIN_RESET : GPIO_PIN_SET);
    RTC_SaveRelayState(Relay_GetStateMask());
}

uint8_t Relay_GetState(uint8_t id)
{
    if (id < 1 || id > RELAY_COUNT) return 0;
    return g_relays[id - 1].state;
}

uint32_t Relay_GetStateMask(void)
{
    uint32_t mask = 0;
    for (uint32_t i = 0; i < RELAY_COUNT; i++) {
        if (g_relays[i].state)
            mask |= (1U << i);
    }
    return mask;
}

void Relay_SetStateMask(uint32_t mask)
{
    for (uint32_t i = 0; i < RELAY_COUNT; i++)
        g_relays[i].state = (mask & (1U << i)) ? 1U : 0U;
}

/* ============================ 传感器 ============================ */
Sensor_Channel_t g_sensors[SENSOR_COUNT] = {
    { 0x01, 0x0004, SCALE_LEVEL, 0.0f, 0, 0, SENSOR_FAIL_THRESH },  /* 液位 */
    { 0x02, 0x0004, SCALE_TEMP,  0.0f, 0, 0, SENSOR_FAIL_THRESH },  /* 温度 */
    { 0x03, 0x0000, SCALE_PH,    0.0f, 0, 0, SENSOR_FAIL_THRESH },  /* pH */
    { 0x04, 0x0000, SCALE_ORP,   0.0f, 0, 0, SENSOR_FAIL_THRESH },  /* ORP */
};

/* 原始整数值 → 工程量 */
static float apply_scale(SensorScale_t type, uint16_t raw)
{
    switch (type) {
        case SCALE_LEVEL: return (float)raw / 9.8f;              /* P=ρgh 标定 */
        case SCALE_TEMP:  return (float)raw * 0.1f;              /* 一位小数 °C */
        case SCALE_PH:    return (float)raw * 0.01f;             /* 两位小数 pH */
        case SCALE_ORP:   return (float)(int16_t)raw;            /* 补码 mV */
        default:          return 0.0f;
    }
}

void Sensors_Poll(void)
{
    for (int i = 0; i < SENSOR_COUNT; i++) {
        uint16_t raw = 0;
        int result = -1;

        for (int retry = 0; retry < 3; retry++) {
            result = Modbus_ReadHolding(g_sensors[i].slave,
                                        g_sensors[i].reg, 1, &raw);
            if (result == 0)
                break;
            delay_us(30000);
        }

        if (result == 0) {
            g_sensors[i].value = apply_scale(g_sensors[i].scale, raw);
            g_sensors[i].fail  = 0;
            g_sensors[i].valid = 1;
        } else if (++g_sensors[i].fail >= g_sensors[i].fail_thresh) {
            g_sensors[i].valid = 0;   /* 连续失败超阈值 → 标记无效 */
        }

        IWDG->KR = 0xAAAA;            /* 喂狗：一次轮询可能耗时较长 */
        delay_us(20000);              /* 帧间间隔 20ms（RS485 需 ≥3.5 字符时间） */
    }
}
