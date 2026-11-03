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
#include "shared/boat_controller_config.h"

static const char *TAG = "BOAT_MAIN";

/* HUSKY_ALGORITHM_ID 最终会写进协议帧的单字节 AlgoID 字段，必须是 0~255。
 * 填错（例如误写成 16 进制 0x1FF 之类）在这里就编译失败，省得现场只看到
 * "切换算法失败"却查不出原因。 */
_Static_assert(HUSKY_ALGORITHM_ID >= 0 && HUSKY_ALGORITHM_ID <= 255,
               "HUSKY_ALGORITHM_ID 必须是 0~255（协议 AlgoID 只有 1 字节）");

/* ---------------- 参数（与原版一致） ---------------- */
#define COMM_TIMEOUT_MS          3000    /* 超过 3 秒没收到桥接板数据 -> 应急 */
#define HUSKY_INTERVAL_MS        100     /* 二哈读取 10 Hz */
#define DEBUG_INTERVAL_MS        500     /* 调试输出 2 Hz */
#define HUSKY_INIT_TIMEOUT_MS    3000    /* 二哈握手最长等待 */
#define MAIN_LOOP_MS             50      /* 主循环 20 Hz */

/* 单目测距参数：distance = OBSTACLE_REAL_WIDTH * FOCAL_LENGTH / 像素宽
 *
 * 这两个数**不是通用常数**，必须按现场标定，否则"20 cm 停车"会整体偏移：
 *   - OBSTACLE_REAL_WIDTH 填当前被救目标（救生圈/浮球）的**真实宽度**（米）。
 *     填 0.10 而实际目标只有 0.05 宽 -> 会在 40 cm 就停；实际 0.20 宽 -> 会顶到
 *     10 cm 才停。
 *   - FOCAL_LENGTH 用一次实测反推：把目标放在已知距离 D 处，读日志里的像素宽
 *     W_px，则 FOCAL = D * W_px / OBSTACLE_REAL_WIDTH。
 *
 * 另外这个距离是"到目标表面"，没有扣除船头到二哈镜头的前伸量；
 * 要更准的话把 VISUAL_STOP_DISTANCE_M 加上这段前伸量。
 */
#define FOCAL_LENGTH             500.0f
#define OBSTACLE_REAL_WIDTH      0.10f

static ground_to_boat_t s_cmd;             /* 最近一次有效命令 */
static boat_to_ground_t s_status;

static bool s_emergency;
static bool s_radio_ready;

/* 本次实际使用的二哈算法 ID。
 * HUSKY_ALGORITHM_ID 非 0 时就是它；等于 0 时表示"自动扫描用户模型段（128~255）"，
 * 由 resolve_algorithm_id() 在二哈就绪后填入。*/
static uint8_t s_algo_id = HUSKY_ALGORITHM_ID;
static bool s_algo_resolved;

static uint32_t s_last_husky_ms;
static uint32_t s_last_debug_ms;

/* 二哈状态
 *
 * s_target_seen：最近一次结果里"有目标框"。
 *   - 默认算法（HUSKY_ALGORITHM_ID=3，内置物体追踪）：表示追踪到了目标；
 *   - 换成设备上部署的自定义模型后：表示"当前帧检测到至少一个目标框"。
 *     驱动只解析 id/algo/x/y/w/h 前 10 字节，自定义模型的类别名不参与解析，
 *     所以这里不区分类别 —— 只要框存在就算"看到目标"，下游导航/测距逻辑不变。
 */
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
    /* s_algo_id 由 resolve_algorithm_id() 解析：
       配置非 0 时就是配置值；配置为 0 时是自动探测到的用户模型 ID（找不到回退 3）。 */
    if (!huskylens_get_result(s_algo_id)) return;

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

/** 解析本次使用的算法 ID。
 *
 *  HUSKY_ALGORITHM_ID != 0：直接用配置值（3=内置物体追踪，或自定义模型 ID 如 131）。
 *  HUSKY_ALGORITHM_ID == 0：自动扫描用户模型段 128~255（协议规定该段属于用户安装模型），
 *  找到就用它，找不到回退内置物体追踪。扫描有 12s 预算，不会把开机卡死。 */
static void resolve_algorithm_id(void)
{
    s_algo_id = HUSKY_ALGORITHM_ID;
    if (HUSKY_ALGORITHM_ID != 0) {
        s_algo_resolved = true;
        return;
    }
    if (!huskylens_is_ready()) return;

    ESP_LOGI(TAG, "HUSKY_ALGORITHM_ID=0：自动探测已安装的自定义模型");
    uint8_t found = huskylens_find_user_algorithm(128, 255, 20000);
    if (found) {
        s_algo_id = found;
        ESP_LOGI(TAG, "自动探测成功，算法 ID=%d（建议把它写进 HUSKY_ALGORITHM_ID 以跳过开机扫描）",
                 (int)found);
    } else {
        s_algo_id = (uint8_t)ALGO_OBJECT_TRACKING;
        ESP_LOGW(TAG, "未探测到用户模型，回退内置物体追踪（算法 ID=%d）", (int)s_algo_id);
    }
    s_algo_resolved = true;
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
        resolve_algorithm_id();
        huskylens_switch_algorithm(s_algo_id);
        vTaskDelay(pdMS_TO_TICKS(500));
        ESP_LOGI(TAG, "HUSKYLENS 2 初始化成功（算法 ID=%d，配置=%d）",
                 (int)s_algo_id, (int)HUSKY_ALGORITHM_ID);
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
        if (!s_algo_resolved) resolve_algorithm_id();
        if (!logged_ok) {
            logged_ok = true;
            huskylens_switch_algorithm(s_algo_id);
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
    /* 打印实际下发的算法 ID，方便现场确认用的是内置算法还是自定义模型。
       若与设备 UI 上看到的不一致，改 shared/boat_controller_config.h 里的
       HUSKY_ALGORITHM_ID 后重新编译。 */
    ESP_LOGI(TAG, "HUSKYLENS 算法 ID=%d（HUSKY_ALGORITHM_ID）", (int)HUSKY_ALGORITHM_ID);

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
