/**
 * 船载主控固件 —— DFRobot Romeo mini ESP32-C3 (DFR1063)
 *
 * 职责（与 Arduino 版 main.ino 行为一致）：
 *   1. 接收桥接板经 ESP-NOW 转发的电脑命令
 *   2. 按 mission_state 执行：待命 / 自主航行 / 释放 / 返航 / 手动遥控
 *   3. HUSKYLENS 2 读取目标（10 Hz），单目测距
 *   4. 通信超时（3 秒）进入应急：见目标追踪，否则原地旋转搜索
 *   5. 以 20 Hz 回传状态给桥接板
 *
 * 相对 Arduino 版的改进：
 *   - 投放舵机真正实现了（原版 releasePayload() 里舵机代码是注释掉的）
 *   - 差速控制改为按比例归一化，避免大角度下 PID 饱和失去控制律
 *   - 释放动作改为非阻塞状态机，不会因 delay(500) 阻塞主循环丢包
 */
#include <math.h>
#include <stdio.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "comm/espnow_link.h"
#include "control/navigation.h"
#include "hw/huskylens.h"
#include "hw/motors.h"
#include "hw/servo_release.h"

static const char *TAG = "BOAT_MAIN";

/* ---------------- 参数（与原版一致） ---------------- */
#define COMM_TIMEOUT_MS          3000    /* 超过 3 秒没收到桥接板数据 -> 应急 */
#define HUSKY_INTERVAL_MS        100     /* 二哈读取 10 Hz */
#define DEBUG_INTERVAL_MS        500     /* 调试输出 2 Hz */
#define HUSKY_INIT_TIMEOUT_MS    3000    /* 二哈握手最长等待 */
#define MAIN_LOOP_MS             50      /* 主循环 20 Hz */

/* 单目测距参数（与原版一致，需按实际目标尺寸标定） */
#define FOCAL_LENGTH             500.0f
#define OBSTACLE_REAL_WIDTH      0.10f

static ground_to_boat_t s_cmd;             /* 最近一次有效命令 */
static boat_to_ground_t s_status;

static bool s_emergency;
static bool s_radio_ready;

static uint32_t s_last_husky_ms;
static uint32_t s_last_debug_ms;

/* 二哈状态 */
static bool s_target_seen;
static int  s_target_x;
static int  s_target_y;
static int  s_target_w;
static float s_vision_dist;

static uint32_t now_ms(void)
{
    return xTaskGetTickCount() * portTICK_PERIOD_MS;
}

/** 读取二哈并更新目标状态与估算距离 */
static void husky_poll(void)
{
    if (now_ms() - s_last_husky_ms < HUSKY_INTERVAL_MS) return;
    s_last_husky_ms = now_ms();

    s_target_seen = false;
    s_target_w = 0;
    s_vision_dist = 999.0f;

    if (!huskylens_is_ready()) return;
    if (!huskylens_get_result(ALGO_OBJECT_TRACKING)) return;

    /* 取面积最大的块，避免误锁小噪点 */
    int best = -1;
    int best_area = 0;
    int n = huskylens_block_count();
    for (int i = 0; i < n; i++) {
        husky_block_t b;
        if (!huskylens_get_block(i, &b)) continue;
        if (b.width <= 0 || b.height <= 0) continue;
        int area = (int)b.width * (int)b.height;
        if (area > best_area) {
            best_area = area;
            best = i;
        }
    }

    if (best >= 0) {
        husky_block_t b;
        if (huskylens_get_block(best, &b)) {
            s_target_x = b.x_center;
            s_target_y = b.y_center;
            s_target_w = b.width;
            s_target_seen = (b.width > 0);

            /* 单目测距：距离 = 真实宽度 * 焦距 / 像素宽度 */
            if (s_target_w > 0) {
                s_vision_dist = (OBSTACLE_REAL_WIDTH * FOCAL_LENGTH) / (float)s_target_w;
                if (s_vision_dist > 5.0f) s_vision_dist = 5.0f;
            }
        }
    }
}

/** 二哈初始化：带超时的握手里程碑。
 *  注意：只在启动时尝试一次是不够的 —— 二哈有启动时间，若它比主控晚就绪，
 *  启动窗口内会读到全 0xFF（从机未驱动总线）。所以这里只做"启动时快试"，
 *  失败后由主循环周期性重试（见 husky_retry_if_needed）。 */
static void husky_init_with_timeout(void)
{
    uint32_t deadline = now_ms() + HUSKY_INIT_TIMEOUT_MS;
    while (!huskylens_is_ready() && now_ms() < deadline) {
        if (huskylens_begin()) break;
        vTaskDelay(pdMS_TO_TICKS(100));
    }

    if (huskylens_is_ready()) {
        huskylens_switch_algorithm(ALGO_OBJECT_TRACKING);
        vTaskDelay(pdMS_TO_TICKS(500));
        ESP_LOGI(TAG, "HUSKYLENS 2 初始化成功");
    } else {
        ESP_LOGW(TAG, "HUSKYLENS 2 暂未就绪，将在运行中继续尝试连接");
    }
}

/** 运行期周期性重试连接二哈（每 2 秒一次），就绪后自动切换算法 */
static void husky_retry_if_needed(void)
{
    static uint32_t last_try_ms;
    static bool logged_ok;

    if (huskylens_is_ready()) return;

    uint32_t t = now_ms();
    if (t - last_try_ms < 2000) return;
    last_try_ms = t;

    if (huskylens_begin()) {
        ESP_LOGI(TAG, "HUSKYLENS 2 已连接（运行期重试成功）");
        if (!logged_ok) {
            logged_ok = true;
            huskylens_switch_algorithm(ALGO_OBJECT_TRACKING);
        }
    } else {
        /* 首次重试仍失败时输出一次通信诊断（内部保证只报一次），
           便于区分"完全没数据"与"有数据但协议不符"。 */
        huskylens_dump_diagnostics();
    }
}

/** 手动遥控：油门 + 转向 合成差速 */
static void handle_manual(void)
{
    int throttle = s_cmd.manual_throttle;
    int steer = s_cmd.manual_steer;

    int left = throttle + steer;
    int right = throttle - steer;

    /* 与原版一致：限幅到 ±200 */
    if (left > MOTOR_PWM_MAX) left = MOTOR_PWM_MAX;
    if (left < -MOTOR_PWM_MAX) left = -MOTOR_PWM_MAX;
    if (right > MOTOR_PWM_MAX) right = MOTOR_PWM_MAX;
    if (right < -MOTOR_PWM_MAX) right = -MOTOR_PWM_MAX;

    motors_set(left, right);
}

static void handle_release(void)
{
    motors_stop();
    if (s_cmd.release_flag == 1) {
        servo_release_trigger();
        s_cmd.release_flag = 0;   /* 单次触发，避免重复投放 */
    }
}

static void debug_print(void)
{
    if (now_ms() - s_last_debug_ms < DEBUG_INTERVAL_MS) return;
    s_last_debug_ms = now_ms();

    const char *mode;
    if (s_emergency) {
        mode = "应急";
    } else {
        switch (s_cmd.mission_state) {
        case MISSION_MANUAL:     mode = "手动"; break;
        case MISSION_AUTONOMOUS:
            if (!navigation_data_valid(&s_cmd)) {
                mode = "自主-二哈搜救";      /* 仅靠二哈：搜索 + 接近 */
            } else {
                mode = navigation_visual_approach_active()
                       ? "自主-二哈靠近" : "自主-坐标导航";
            }
            break;
        case MISSION_RELEASE:    mode = "释放"; break;
        case MISSION_RETURN:     mode = "返航"; break;
        default:                 mode = "待命"; break;
        }
    }

    int l = 0, r = 0;
    motors_get(&l, &r);

    uint32_t recv = 0, fail = 0;
    espnow_link_counters(&recv, &fail);

    ESP_LOGI(TAG, "[状态] %s | 二哈:%s%s | 电机 L=%d R=%d | 遥控 %lu/%lu | 释放 %lu",
             mode,
             huskylens_is_ready() ? (s_target_seen ? "有目标" : "无目标") : "未连接",
             s_target_seen ? "" : "",
             l, r,
             (unsigned long)recv, (unsigned long)fail,
             (unsigned long)servo_release_count());

    if (s_target_seen) {
        ESP_LOGI(TAG, "        目标 X=%d Y=%d 宽=%d 估算距离=%.2f m",
                 s_target_x, s_target_y, s_target_w, s_vision_dist);
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "DFR1063 启动（ESP-IDF）");

    /* 硬件先初始化，且保证电机处于停止态 */
    motors_init();
    motors_stop();
    servo_release_init();

    espnow_link_start();
    s_radio_ready = true;

    husky_init_with_timeout();

    /* 用一个"无限久以前"的时间，让第一次判定就进入应急兜底 */
    ESP_LOGI(TAG, "船载 MAC: %s  桥接板 MAC: %s",
             espnow_link_own_mac_str(), espnow_link_bridge_mac_str());
    ESP_LOGI(TAG, "初始化完成，等待桥接板命令...");

    while (1) {
        /* 1. 取新命令（有新帧才覆盖，否则沿用上一条） */
        ground_to_boat_t incoming;
        if (espnow_link_take_command(&incoming)) {
            bool was_emergency = s_emergency;
            s_cmd = incoming;
            if (was_emergency) {
                s_emergency = false;
                navigation_reset();
                ESP_LOGI(TAG, "通信恢复，退出应急模式");
            }
        }

        /* 2. 若二哈尚未就绪则周期性重试连接，再读取目标 */
        husky_retry_if_needed();
        husky_poll();

        /* 3. 推进释放状态机（非阻塞） */
        servo_release_tick();

        /* 4. 判断通信是否超时 */
        uint32_t silence = espnow_link_silence_ms();
        bool comm_timeout = (silence == UINT32_MAX) || (silence > COMM_TIMEOUT_MS);

        if (comm_timeout) {
            if (!s_emergency) {
                s_emergency = true;
                navigation_reset();
                ESP_LOGW(TAG, "=== 通信中断！进入应急模式 ===");
            }
            navigation_emergency(s_vision_dist, s_target_seen, s_target_x);
        } else {
            if (s_cmd.mission_state != MISSION_AUTONOMOUS) {
                /* 离开自主模式时清掉末端阶段状态 */
                navigation_reset();
            }

            switch (s_cmd.mission_state) {
            case MISSION_AUTONOMOUS:
                /* 两种自主行为自动选择：
                   - 电脑提供了有效坐标 -> 坐标导航（依赖 UVC 全局定位）
                   - 没有坐标           -> 纯二哈视觉搜救（识别到就自主前往） */
                if (navigation_data_valid(&s_cmd)) {
                    navigation_autonomous(&s_cmd, s_vision_dist, s_target_seen, s_target_x);
                } else {
                    navigation_vision_search(s_vision_dist, s_target_seen, s_target_x);
                }
                break;
            case MISSION_RELEASE:
                handle_release();
                break;
            case MISSION_MANUAL:
                handle_manual();
                break;
            case MISSION_RETURN:      /* 返航尚未实现，按待命处理（与原版一致） */
            default:
                motors_stop();
                break;
            }
        }

        /* 5. 回传状态（桥接板在线时才发） */
        if (!comm_timeout) {
            int l = 0, r = 0;
            motors_get(&l, &r);
            s_status.boat_heading = -1.0f;   /* 当前无罗盘/IMU，不伪造航向 */
            s_status.left_motor_speed = l;
            s_status.right_motor_speed = r;
            s_status.target_detected = s_target_seen ? 1 : 0;
            s_status.local_target_x = s_target_x;
            s_status.local_target_y = s_target_y;
            s_status.estimated_dist_m = s_vision_dist;
            s_status.emergency_mode = s_emergency ? 1 : 0;
            espnow_link_send_status(&s_status);
        }

        /* 6. 节流调试输出 */
        debug_print();

        vTaskDelay(pdMS_TO_TICKS(MAIN_LOOP_MS));
    }
}
