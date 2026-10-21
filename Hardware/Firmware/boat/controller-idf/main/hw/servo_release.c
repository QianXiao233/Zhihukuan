/**
 * 载荷释放机构实现（MG90S 舵机，非阻塞状态机）
 */
#include "servo_release.h"

#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "BOAT_SERVO";

#define SERVO_GPIO        6
#define SERVO_LEDC_TIMER  LEDC_TIMER_0
#define SERVO_LEDC_MODE   LEDC_LOW_SPEED_MODE
#define SERVO_LEDC_CH     LEDC_CHANNEL_0
#define SERVO_LEDC_RES    LEDC_TIMER_13_BIT

#define SERVO_FREQ_HZ     50
#define SERVO_PERIOD_US   20000        /* 50 Hz -> 20 ms */
#define SERVO_MIN_US      500          /* 0°   */
#define SERVO_MAX_US      2500         /* 180° */

#define SERVO_LOCKED_DEG  0            /* 锁定（插销到位） */
#define SERVO_RELEASE_DEG 90           /* 释放（拉出插销） */

#define RELEASE_HOLD_MS   500          /* 保持时间，确保插销完全脱出 */

typedef enum {
    RELEASE_IDLE = 0,
    RELEASE_PULLING,
    RELEASE_RETURNING,
} release_state_t;

static release_state_t s_state = RELEASE_IDLE;
static uint32_t s_state_started_ms;
static uint32_t s_release_count;

static uint32_t now_ms(void)
{
    return xTaskGetTickCount() * portTICK_PERIOD_MS;
}

/** 角度 -> LEDC 占空比（13 bit，周期 20 ms） */
static uint32_t deg_to_duty(int deg)
{
    if (deg < 0) deg = 0;
    if (deg > 180) deg = 180;
    uint32_t us = SERVO_MIN_US + (uint32_t)(SERVO_MAX_US - SERVO_MIN_US) * deg / 180;
    return (uint32_t)((uint64_t)us * ((1 << SERVO_LEDC_RES) - 1) / SERVO_PERIOD_US);
}

static void servo_write_deg(int deg)
{
    uint32_t duty = deg_to_duty(deg);
    ledc_set_duty(SERVO_LEDC_MODE, SERVO_LEDC_CH, duty);
    ledc_update_duty(SERVO_LEDC_MODE, SERVO_LEDC_CH);
}

void servo_release_init(void)
{
    ledc_timer_config_t timer = {
        .speed_mode = SERVO_LEDC_MODE,
        .duty_resolution = SERVO_LEDC_RES,
        .timer_num = SERVO_LEDC_TIMER,
        .freq_hz = SERVO_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));

    ledc_channel_config_t ch = {
        .gpio_num = SERVO_GPIO,
        .speed_mode = SERVO_LEDC_MODE,
        .channel = SERVO_LEDC_CH,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = SERVO_LEDC_TIMER,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ch));

    /* 上电回到锁定位置 */
    servo_write_deg(SERVO_LOCKED_DEG);
    s_state = RELEASE_IDLE;
    ESP_LOGI(TAG, "舵机初始化完成 (GPIO%d, 50Hz, 锁定在 %d°)", SERVO_GPIO, SERVO_LOCKED_DEG);
}

bool servo_release_trigger(void)
{
    if (s_state != RELEASE_IDLE) {
        ESP_LOGW(TAG, "释放动作进行中，忽略重复触发");
        return false;
    }
    s_state = RELEASE_PULLING;
    s_state_started_ms = now_ms();
    servo_write_deg(SERVO_RELEASE_DEG);
    ESP_LOGI(TAG, "释放机构动作：拉出插销 (%d°)", SERVO_RELEASE_DEG);
    return true;
}

void servo_release_tick(void)
{
    if (s_state == RELEASE_IDLE) return;

    uint32_t elapsed = now_ms() - s_state_started_ms;

    if (s_state == RELEASE_PULLING && elapsed >= RELEASE_HOLD_MS) {
        /* 保持时间到，舵机回位（插销由弹簧复位） */
        servo_write_deg(SERVO_LOCKED_DEG);
        s_state = RELEASE_RETURNING;
        s_state_started_ms = now_ms();
        ESP_LOGI(TAG, "释放完成，舵机回位");
        s_release_count++;
    } else if (s_state == RELEASE_RETURNING && elapsed >= 300) {
        s_state = RELEASE_IDLE;
    }
}

bool servo_release_busy(void)
{
    return s_state != RELEASE_IDLE;
}

uint32_t servo_release_count(void)
{
    return s_release_count;
}
