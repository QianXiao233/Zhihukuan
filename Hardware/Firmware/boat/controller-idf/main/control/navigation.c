/**
 * 航行控制实现
 */
#include "navigation.h"

#include <math.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "motors.h"

static const char *TAG = "BOAT_NAV";

/* ---------------- 参数（与原 Arduino 版一致） ---------------- */
#define COARSE_ARRIVAL_RADIUS_M   0.15f   /* 进入该半径切换二哈精细靠近。
                                             * 注意：二哈未接入/未识别到目标时，进入末端会
                                             * 依赖 target_seen，看不到就停车或原地搜索。
                                             * 上位机坐标已经足够准的场合可以把这个值调小，
                                             * 让坐标导航一直开到很近。 */
#define VISUAL_STOP_DISTANCE_M    0.20f   /* 视觉测距到该值停车 */
#define VISION_FRAME_CENTER_PX    320.0f  /* 画面横向中心（HUSKYLENS 2 为 640x480） */

/* 末端阶段丢目标的处理节奏。
 * 原实现是"看不到目标就停车并永久停住"，二哈没连上 / 目标在船后方 / 被船身挡住时
 * 船会卡在离目标 40 cm 的地方，救援直接中断。现在分三档：
 *   短暂丢帧   -> 先停车，避免盲冲
 *   持续 1.5 s -> 原地慢速旋转搜索
 *   持续 8 s   -> 放弃末端阶段，退回坐标导航重新对准（带 3 s 冷却，防止来回抖动）
 */
#define VISUAL_LOST_SEARCH_MS     1500
#define VISUAL_LOST_GIVEUP_MS     8000
#define VISUAL_REACQUIRE_COOLDOWN_MS 3000

/* PID */
/* ---- 速度参数（现场按池子大小/水阻调，直接改这里）----
 * MOTOR_PWM_MAX 是 ±200；下面这些是"基础速度"，实际输出还会叠加转向修正。
 * 1.2 m 的沙盘池里 100 已经偏快（船头到池壁不到 0.6 m），起步建议 55~70。
 */
#define NAV_CRUISE_SPEED        60    /* 坐标导航基础速度（远距离巡航） */
#define NAV_CRUISE_LIMIT        110   /* 巡航时单轮上限 */
#define NAV_SLOW_RADIUS_M       0.45f /* 进入该半径开始减速，避免贴脸冲 */
#define NAV_SLOW_SPEED          40    /* 减速后的基础速度 */
#define NAV_SLOW_LIMIT          80
#define NAV_TURN_GAIN           1.2f  /* 转向修正增益（越小越柔和） */
#define NAV_VISUAL_SPEED        45    /* 二哈末端阶段的推进速度 */
#define NAV_VISUAL_LIMIT        85

static const float KP = 2.0f;
static const float KI = 0.0f;
static const float KD = 0.5f;

static float s_integral;
static float s_last_error;

/* 末端视觉阶段状态 */
static bool  s_visual_active;
static bool  s_approach_initialized;
static float s_approach_x;
static float s_approach_y;
static uint32_t s_visual_lost_ms;          /* 本次连续丢目标的起始时刻（0 = 没丢） */
static uint32_t s_visual_cooldown_until_ms;/* 放弃末端后的重新进入冷却截止时刻 */

static uint32_t now_ms(void)
{
    return xTaskGetTickCount() * portTICK_PERIOD_MS;
}

static int clamp_int(int v, int lo, int hi)
{
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

static float clamp_f(float v, float lo, float hi)
{
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

void navigation_reset(void)
{
    s_integral = 0;
    s_last_error = 0;
    s_visual_active = false;
    s_approach_initialized = false;
    s_visual_lost_ms = 0;
    s_visual_cooldown_until_ms = 0;
}

bool navigation_data_valid(const ground_to_boat_t *cmd)
{
    if (cmd == NULL) return false;

    const float v[5] = {cmd->boat_x, cmd->boat_y, cmd->boat_heading,
                        cmd->target_x, cmd->target_y};
    for (int i = 0; i < 5; i++) {
        if (!isfinite(v[i])) return false;
    }

    /* 池子 1.2 m；坐标必须落在合理范围（留一点余量）。航向 0-360。 */
    if (cmd->boat_x < 0.0f || cmd->boat_x > 1.5f) return false;
    if (cmd->boat_y < 0.0f || cmd->boat_y > 1.5f) return false;
    if (cmd->target_x < 0.0f || cmd->target_x > 1.5f) return false;
    if (cmd->target_y < 0.0f || cmd->target_y > 1.5f) return false;
    if (cmd->boat_heading < 0.0f || cmd->boat_heading > 360.0f) return false;

    /* 全部为 0 视为"网页没填"，此时没有定位信息可用 → 走二哈自主搜救。
       真实的船和目标同时都在原点是不可能的。 */
    if (cmd->boat_x == 0.0f && cmd->boat_y == 0.0f &&
        cmd->target_x == 0.0f && cmd->target_y == 0.0f) {
        return false;
    }
    return true;
}

/**
 * 把一个期望的差速指令下发。
 *
 * 注意：原 Arduino 版是分别对左右轮做 constrain(0,180)，
 * 当 |correction| > base 时会一侧饱和到 0、另一侧到 180，
 * 大角度下失去控制律。这里改为**按比例归一化**：
 * 先算出左右轮转速，若超出上限则整体缩放，保持差速比例。
 */
static void drive_differential(int base_speed, int correction, int limit)
{
    int left  = base_speed + correction;
    int right = base_speed - correction;

    /* 归一化：保证最大幅值不超过 limit，同时保留差速比例 */
    int peak = abs(left) > abs(right) ? abs(left) : abs(right);
    if (peak > limit && peak > 0) {
        left  = left  * limit / peak;
        right = right * limit / peak;
    }

    left  = clamp_int(left, -limit, limit);
    right = clamp_int(right, -limit, limit);
    motors_set(left, right);
}

void navigation_autonomous(const ground_to_boat_t *cmd,
                           float vision_dist,
                           bool target_seen,
                           int target_x_px)
{
    if (cmd == NULL) {
        motors_stop();
        return;
    }

    /* 目标点变化超过 30 cm 视为新目标，重置末端阶段 */
    if (!s_approach_initialized ||
        fabsf(cmd->target_x - s_approach_x) > 0.30f ||
        fabsf(cmd->target_y - s_approach_y) > 0.30f) {
        s_approach_x = cmd->target_x;
        s_approach_y = cmd->target_y;
        s_approach_initialized = true;
        s_visual_active = false;
    }

    /* 与目标的平面距离 */
    float dx = cmd->target_x - cmd->boat_x;
    float dy = cmd->target_y - cmd->boat_y;
    float dist = sqrtf(dx * dx + dy * dy);

    uint32_t t = now_ms();

    /* 进入末端区域的判据；放弃末端后有 3 s 冷却，避免"刚退回坐标导航又立刻切回"
       在两个状态之间来回抖。 */
    if (!s_visual_active && dist <= COARSE_ARRIVAL_RADIUS_M &&
        (int32_t)(t - s_visual_cooldown_until_ms) >= 0) {
        s_visual_active = true;
        s_visual_lost_ms = 0;
        s_integral = 0;
        s_last_error = 0;
        ESP_LOGI(TAG, "进入末端区域（%.2f m），切换二哈精细靠近", dist);
    }

    /* ---- 末端视觉阶段 ---- */
    if (s_visual_active) {
        if (!target_seen) {
            if (s_visual_lost_ms == 0) s_visual_lost_ms = t;
            uint32_t lost = t - s_visual_lost_ms;

            if (lost >= VISUAL_LOST_GIVEUP_MS) {
                /* 长时间看不到目标（二哈没连上/目标在船后/被船身挡住）：
                   不再原地死等，退回坐标导航重新对准。 */
                s_visual_active = false;
                s_visual_lost_ms = 0;
                s_integral = 0;
                s_last_error = 0;
                s_visual_cooldown_until_ms = t + VISUAL_REACQUIRE_COOLDOWN_MS;
                ESP_LOGW(TAG, "末端 %lu ms 未见目标，退回坐标导航重新对准",
                         (unsigned long)lost);
            } else if (lost >= VISUAL_LOST_SEARCH_MS) {
                /* 原地慢速旋转搜索：左轮前进、右轮后退 = 向右转 */
                motors_set(45, -45);
                return;
            } else {
                /* 刚丢帧：先停车，避免按旧画面盲冲 */
                motors_stop();
                return;
            }
        } else {
            s_visual_lost_ms = 0;
            if (vision_dist <= VISUAL_STOP_DISTANCE_M) {
                motors_stop();
                return;
            }
            float local_error = (target_x_px - VISION_FRAME_CENTER_PX) / VISION_FRAME_CENTER_PX;
            int correction = (int)(local_error * 90.0f);
            drive_differential(NAV_VISUAL_SPEED, correction, NAV_VISUAL_LIMIT);
            return;
        }
    }

    /* ---- 坐标导航阶段（航向 PID） ---- */
    /* 期望航向：以 +Y 为 0°，顺时针为正（与原版 atan2(dx, dy) 一致） */
    float desired = atan2f(dx, dy) * 180.0f / (float)M_PI;
    if (desired < 0) desired += 360.0f;

    float error = desired - cmd->boat_heading;
    if (error > 180.0f)  error -= 360.0f;
    if (error < -180.0f) error += 360.0f;

    s_integral = clamp_f(s_integral + error, -500.0f, 500.0f);
    float derivative = error - s_last_error;
    float correction = KP * error + KI * s_integral + KD * derivative;
    s_last_error = error;

    /* 按距离分档减速：远距离巡航、快接近时降速，避免到点前冲过头撞池壁 */
    int base_speed = (dist <= NAV_SLOW_RADIUS_M) ? NAV_SLOW_SPEED : NAV_CRUISE_SPEED;
    int limit      = (dist <= NAV_SLOW_RADIUS_M) ? NAV_SLOW_LIMIT : NAV_CRUISE_LIMIT;
    /* 转向修正限幅，避免误差大时一侧轮子打满导致原地打转 */
    int corr = (int)(correction * NAV_TURN_GAIN);
    if (corr >  limit) corr =  limit;
    if (corr < -limit) corr = -limit;
    drive_differential(base_speed, corr, limit);
}

/**
 * 二哈视觉伺服核心：只依赖二哈，不需要任何全局定位。
 *
 *   没看到目标 -> 原地慢速旋转搜索
 *   看到目标   -> 按画面横向偏差转向 + 前进，距离 <= 20 cm 停车
 *
 * navigation_vision_search()（自主搜救）与 navigation_emergency()（通信超时）
 * 共用本函数，保证两种情况下行为一致。
 */
static void vision_servo_step(float vision_dist, bool target_seen, int target_x_px)
{
    if (!target_seen) {
        /* 原地慢速旋转搜索：左右轮反向 */
        motors_set(70, -70);
        return;
    }

    if (vision_dist <= VISUAL_STOP_DISTANCE_M) {
        motors_stop();
        return;
    }

    /* 目标偏右 -> local_error > 0 -> 左轮加速右轮减速 -> 向右转 */
    float local_error = (target_x_px - VISION_FRAME_CENTER_PX) / VISION_FRAME_CENTER_PX;
    if (local_error > 1.0f)  local_error = 1.0f;
    if (local_error < -1.0f) local_error = -1.0f;

    int correction = (int)(local_error * 80.0f);
    drive_differential(80, correction, 150);
}

void navigation_vision_search(float vision_dist, bool target_seen, int target_x_px)
{
    vision_servo_step(vision_dist, target_seen, target_x_px);
}

void navigation_emergency(float vision_dist, bool target_seen, int target_x_px)
{
    vision_servo_step(vision_dist, target_seen, target_x_px);
}

bool navigation_visual_approach_active(void)
{
    return s_visual_active;
}
