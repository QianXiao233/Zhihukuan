/**
 * 航行控制实现
 */
#include "navigation.h"

#include <math.h>

#include "esp_log.h"
#include "motors.h"

static const char *TAG = "BOAT_NAV";

/* ---------------- 参数（与原 Arduino 版一致） ---------------- */
#define COARSE_ARRIVAL_RADIUS_M   0.40f   /* 进入该半径切换二哈精细靠近 */
#define VISUAL_STOP_DISTANCE_M    0.20f   /* 视觉测距到该值停车 */
#define VISION_FRAME_CENTER_PX    320.0f  /* 画面横向中心 */

/* PID */
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

    if (!s_visual_active && dist <= COARSE_ARRIVAL_RADIUS_M) {
        s_visual_active = true;
        s_integral = 0;
        s_last_error = 0;
        ESP_LOGI(TAG, "进入末端区域（%.2f m），切换二哈精细靠近", dist);
    }

    /* ---- 末端视觉阶段 ---- */
    if (s_visual_active) {
        if (!target_seen) {
            motors_stop();
            return;
        }
        if (vision_dist <= VISUAL_STOP_DISTANCE_M) {
            motors_stop();
            return;
        }
        float local_error = (target_x_px - VISION_FRAME_CENTER_PX) / VISION_FRAME_CENTER_PX;
        int correction = (int)(local_error * 90.0f);
        drive_differential(75, correction, 140);
        return;
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

    drive_differential(100, (int)correction, 180);
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
