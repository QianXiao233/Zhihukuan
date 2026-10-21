/**
 * 双电机驱动实现
 */
#include "motors.h"

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"

#include "shared/boat_controller_config.h"

static const char *TAG = "BOAT_MOTORS";

/* 引脚定义（与 DFR1063 接线一致） */
#define M1_PWM_GPIO   0
#define M1_DIR_GPIO   1
#define M2_PWM_GPIO   2
#define M2_DIR_GPIO   10

/* 电机 PWM：20 kHz、10 bit（0..1023），人耳听不到啸叫 */
#define MOTOR_LEDC_FREQ_HZ   20000
#define MOTOR_LEDC_RES       LEDC_TIMER_10_BIT
#define MOTOR_DUTY_MAX       ((1 << MOTOR_LEDC_RES) - 1)

/* 使用独立 timer，避免与舵机的 50 Hz 冲突 */
#define MOTOR_TIMER          LEDC_TIMER_1
#define MOTOR_MODE           LEDC_LOW_SPEED_MODE
#define MOTOR_CH_M1          LEDC_CHANNEL_1
#define MOTOR_CH_M2          LEDC_CHANNEL_2

static int s_left = 0;
static int s_right = 0;

static void motor_channel_setup(ledc_channel_t ch, int gpio)
{
    ledc_channel_config_t cfg = {
        .gpio_num = gpio,
        .speed_mode = MOTOR_MODE,
        .channel = ch,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = MOTOR_TIMER,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&cfg));
}

static int clamp_pwm(int v)
{
    if (v > MOTOR_PWM_MAX) return MOTOR_PWM_MAX;
    if (v < -MOTOR_PWM_MAX) return -MOTOR_PWM_MAX;
    return v;
}

/** 把 -200..200 映射到 0..1023 并写入，同时设置方向脚 */
static void apply_motor(int pwm, ledc_channel_t ch, int dir_gpio)
{
    int v = clamp_pwm(pwm);
    bool forward = (v >= 0);
    int mag = v < 0 ? -v : v;

    uint32_t duty = (uint32_t)((int64_t)mag * MOTOR_DUTY_MAX / MOTOR_PWM_MAX);

#if !ENABLE_MOTOR_OUTPUT
    /* 陆地调试安全模式：强制不转 */
    duty = 0;
#endif

    /* 方向脚：与 Arduino 版一致，forward -> LOW，reverse -> HIGH */
    gpio_set_level(dir_gpio, forward ? 0 : 1);
    ledc_set_duty(MOTOR_MODE, ch, duty);
    ledc_update_duty(MOTOR_MODE, ch);
}

void motors_init(void)
{
    gpio_config_t dir_cfg = {
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = (1ULL << M1_DIR_GPIO) | (1ULL << M2_DIR_GPIO),
    };
    ESP_ERROR_CHECK(gpio_config(&dir_cfg));

    ledc_timer_config_t timer = {
        .speed_mode = MOTOR_MODE,
        .duty_resolution = MOTOR_LEDC_RES,
        .timer_num = MOTOR_TIMER,
        .freq_hz = MOTOR_LEDC_FREQ_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));

    motor_channel_setup(MOTOR_CH_M1, M1_PWM_GPIO);
    motor_channel_setup(MOTOR_CH_M2, M2_PWM_GPIO);

    motors_stop();

#if !ENABLE_MOTOR_OUTPUT
    ESP_LOGW(TAG, "电机输出已禁用（陆地调试模式）");
#else
    ESP_LOGI(TAG, "电机初始化完成 (20kHz/%dbit)", (int)MOTOR_LEDC_RES);
#endif
}

void motors_set(int left, int right)
{
    s_left = clamp_pwm(left);
    s_right = clamp_pwm(right);
    apply_motor(s_left, MOTOR_CH_M1, M1_DIR_GPIO);
    apply_motor(s_right, MOTOR_CH_M2, M2_DIR_GPIO);
}

void motors_stop(void)
{
    s_left = 0;
    s_right = 0;
    ledc_set_duty(MOTOR_MODE, MOTOR_CH_M1, 0);
    ledc_update_duty(MOTOR_MODE, MOTOR_CH_M1);
    ledc_set_duty(MOTOR_MODE, MOTOR_CH_M2, 0);
    ledc_update_duty(MOTOR_MODE, MOTOR_CH_M2);
}

void motors_get(int *left, int *right)
{
    if (left) *left = s_left;
    if (right) *right = s_right;
}
