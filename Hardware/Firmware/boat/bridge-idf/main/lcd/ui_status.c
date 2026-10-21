/**
 * 桥接板状态屏实现
 */
#include "ui_status.h"

#include <stdio.h>
#include <string.h>

#include "esp_timer.h"
#include "lvgl.h"

#include "comm/espnow_bridge.h"
#include "diag.h"
#include "lcd/LVGL_Driver.h"
#include "protocol/serial_protocol.h"

/* ---------------- 配色 ---------------- */
#define COL_BG      0x0B1016
#define COL_STRIP   0x00C8E0
#define COL_CARD    0x16212B
#define COL_LABEL   0x93A4B0
#define COL_VALUE   0x4DD0E1
#define COL_HEADER  0xE8F4F8
#define COL_OK      0x4CAF50
#define COL_WARN    0xFFC107
#define COL_BAD     0xEF5350
#define COL_IDLE    0x546E7A

/* 320 宽：卡片 304 + 左右各 8 */
#define CARD_H      20
#define ROW_GAP     3
#define ROW_TOP     32

/* 左列（6 行）与右列（诊断）的横向布局。
   屏宽 320：左列 8..194（186 宽），右列 200..312（112 宽），中间留 6 px。 */
#define LEFT_X      8
#define LEFT_W      186
#define RIGHT_X     200
#define RIGHT_W     112

/* 屏上各数值控件 */
static lv_obj_t *s_link_dot;
static lv_obj_t *s_link_text;
static lv_obj_t *s_send_text;
static lv_obj_t *s_boat_text;
static lv_obj_t *s_motor_text;
static lv_obj_t *s_target_text;
static lv_obj_t *s_dist_text;
/* 诊断行：芯片结温 + CPU 占用（排查发烫用，可直接看屏读数） */
static lv_obj_t *s_temp_text;
static lv_obj_t *s_cpu_text;

/* 缓存上一次写入的字符串，值未变就不调用 LVGL，减少重绘 */
static char s_cache[10][24];
/* 各槽位上次写入时刻，用于按秒节流（见 changed_at_most_every） */
static uint32_t s_slot_last_ms[10];
/* 链路状态点的当前颜色，用于避免无条件调用 lv_obj_set_style_* */
static uint32_t s_dot_color_cached;

static bool changed(int slot, const char *text)
{
    if (strncmp(s_cache[slot], text, sizeof(s_cache[0])) == 0) return false;
    s_slot_last_ms[slot] = xTaskGetTickCount() * portTICK_PERIOD_MS;
    strncpy(s_cache[slot], text, sizeof(s_cache[0]) - 1);
    s_cache[slot][sizeof(s_cache[0]) - 1] = '\0';
    return true;
}

/**
 * 建一条数据行，返回右侧数值 label。
 *
 * 屏只有 172 px 高，只能放 6 行（6*23 + 32 = 170）。诊断信息因此不能往下堆，
 * 必须并排放到右侧一列 —— 这是本函数支持自定义 x/宽度的原因。
 */
static lv_obj_t *row_create_at(lv_obj_t *parent, lv_coord_t x, lv_coord_t y,
                               lv_coord_t w, const char *name)
{
    lv_obj_t *card = lv_obj_create(parent);
    lv_obj_remove_style_all(card);
    lv_obj_set_size(card, w, CARD_H);
    lv_obj_set_pos(card, x, y);
    lv_obj_set_style_bg_color(card, lv_color_hex(COL_CARD), 0);
    lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
    lv_obj_set_style_radius(card, 3, 0);
    lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *label = lv_label_create(card);
    lv_label_set_text(label, name);
    lv_obj_set_style_text_color(label, lv_color_hex(COL_LABEL), 0);
    lv_obj_set_pos(label, 8, 5);

    lv_obj_t *value = lv_label_create(card);
    lv_label_set_text(value, "--");
    lv_obj_set_style_text_color(value, lv_color_hex(COL_VALUE), 0);
    lv_obj_align(value, LV_ALIGN_RIGHT_MID, -8, 0);

    return value;
}

/** 建一条全宽数据行（左列用） */
static lv_obj_t *row_create(lv_obj_t *parent, lv_coord_t y, const char *name)
{
    return row_create_at(parent, LEFT_X, y, LEFT_W, name);
}

/** 建一个圆形状态指示点 */
static lv_obj_t *dot_create(lv_obj_t *parent, lv_coord_t x, lv_coord_t y)
{
    lv_obj_t *dot = lv_obj_create(parent);
    lv_obj_remove_style_all(dot);
    lv_obj_set_size(dot, 8, 8);
    lv_obj_set_pos(dot, x, y);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, lv_color_hex(COL_IDLE), 0);
    lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
    return dot;
}

void ui_status_create(void)
{
    lv_obj_t *scr = lv_scr_act();
    lv_obj_clear_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_set_style_bg_color(scr, lv_color_hex(COL_BG), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);

    /* 顶部强调条 */
    lv_obj_t *strip = lv_obj_create(scr);
    lv_obj_remove_style_all(strip);
    lv_obj_set_size(strip, EXAMPLE_LCD_H_RES, 2);
    lv_obj_set_pos(strip, 0, 0);
    lv_obj_set_style_bg_color(strip, lv_color_hex(COL_STRIP), 0);
    lv_obj_set_style_bg_opa(strip, LV_OPA_COVER, 0);

    /* 标题 */
    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "BRIDGE");
    lv_obj_set_style_text_color(title, lv_color_hex(COL_HEADER), 0);
    lv_obj_set_pos(title, 10, 7);

    /* 标题右侧：本板 ESP-NOW MAC（换板子时一眼能看出对不对） */
    lv_obj_t *mac = lv_label_create(scr);
    lv_label_set_text(mac, espnow_bridge_own_mac_str());
    lv_obj_set_style_text_color(mac, lv_color_hex(COL_LABEL), 0);
    lv_obj_align(mac, LV_ALIGN_TOP_RIGHT, -10, 7);

    /* 行 1：电脑串口链路（左侧另有状态点，用颜色表示通断） */
    s_link_text  = row_create(scr, ROW_TOP, "PC LINK");
    s_link_dot   = dot_create(scr, LEFT_X + LEFT_W - 22, ROW_TOP + 6);
    /* 行 2：ESP-NOW 发送统计 */
    s_send_text  = row_create(scr, ROW_TOP + (CARD_H + ROW_GAP) * 1, "ESPNOW TX");
    /* 行 3：船端回传静默 */
    s_boat_text  = row_create(scr, ROW_TOP + (CARD_H + ROW_GAP) * 2, "BOAT RX");
    /* 行 4：电机 */
    s_motor_text = row_create(scr, ROW_TOP + (CARD_H + ROW_GAP) * 3, "MOTOR");
    /* 行 5：目标 */
    s_target_text= row_create(scr, ROW_TOP + (CARD_H + ROW_GAP) * 4, "TARGET");
    /* 行 6：距离 */
    s_dist_text  = row_create(scr, ROW_TOP + (CARD_H + ROW_GAP) * 5, "DISTANCE");

    /* ---- 右列：诊断 ----
       放在右侧而不是往下堆，因为屏高只有 172 px，往下第 7 行就会超出屏幕。
       温度/CPU 显示到屏上是为了绕开串口：这块板的 USB-Serial-JTAG 读取不稳定，
       直接读屏比反复折腾串口可靠。 */
    s_temp_text  = row_create_at(scr, RIGHT_X, ROW_TOP, RIGHT_W, "TEMP C");
    s_cpu_text   = row_create_at(scr, RIGHT_X, ROW_TOP + (CARD_H + ROW_GAP) * 1,
                                 RIGHT_W, "CPU %");

    memset(s_cache, 0, sizeof(s_cache));
}

/** 按槽位节流：文本至少间隔 min_interval_ms 才允许写一次 LVGL */
static bool changed_at_most_every(int slot, const char *text, uint32_t min_interval_ms)
{
    uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
    if (s_cache[slot][0] != '\0' && (now - s_slot_last_ms[slot]) < min_interval_ms) {
        return false;   /* 冷却期内直接跳过，先不做字符串比较 */
    }
    if (strcmp(s_cache[slot], text) == 0) return false;

    s_slot_last_ms[slot] = now;
    strncpy(s_cache[slot], text, sizeof(s_cache[0]) - 1);
    s_cache[slot][sizeof(s_cache[0]) - 1] = '\0';
    return true;
}

void ui_status_update(void)
{
    char buf[48];

    /* ---- 电脑串口链路 ----
       命令计数每次都变；按 1 秒节流，否则每 100 ms 都会触发一次 LVGL 重绘。 */
    bool host_alive = serial_protocol_host_alive();
    uint32_t cmds = serial_protocol_command_count();
    if (cmds == 0) {
        snprintf(buf, sizeof(buf), "WAIT");
    } else if (host_alive) {
        snprintf(buf, sizeof(buf), "OK  #%lu", (unsigned long)cmds);
    } else {
        snprintf(buf, sizeof(buf), "IDLE %lums", (unsigned long)serial_protocol_host_silence_ms());
    }
    if (changed_at_most_every(0, buf, 1000)) lv_label_set_text(s_link_text, buf);

    /* 状态点：只在颜色真的变化时才设置样式。
       原来是无条件调用 —— lv_obj_set_style_* 会走对象失效流程，
       即使颜色没变也可能导致重绘。 */
    uint32_t dot_color = cmds == 0 ? COL_IDLE : (host_alive ? COL_OK : COL_WARN);
    if (dot_color != s_dot_color_cached) {
        s_dot_color_cached = dot_color;
        lv_obj_set_style_bg_color(s_link_dot, lv_color_hex(dot_color), 0);
    }

    /* ---- ESP-NOW 发送统计（计数每次都在变，按 1 秒节流） ---- */
    uint32_t sent = 0, recv = 0, fail = 0;
    espnow_bridge_counters(&sent, &recv, &fail);
    snprintf(buf, sizeof(buf), "%lu ok / %lu fail", (unsigned long)sent, (unsigned long)fail);
    if (changed_at_most_every(1, buf, 1000)) lv_label_set_text(s_send_text, buf);

    /* ---- 船端回传静默 ----
       这里原来是功耗热点：silence 毫秒数每次调用都不同，导致 changed()
       的去重完全失效，每 100 ms 必然重绘一次。现在按 1 秒节流。 */
    uint32_t silence = espnow_bridge_boat_silence_ms();
    if (silence == UINT32_MAX) {
        snprintf(buf, sizeof(buf), "NO DATA");
    } else {
        snprintf(buf, sizeof(buf), "%lums  #%lu", (unsigned long)silence, (unsigned long)recv);
    }
    if (changed_at_most_every(2, buf, 1000)) lv_label_set_text(s_boat_text, buf);

    /* ---- 船端遥测 ---- */
    boat_to_ground_t st;
    if (espnow_bridge_get_status(&st)) {
        snprintf(buf, sizeof(buf), "%d / %d", st.left_motor_speed, st.right_motor_speed);
        if (changed(3, buf)) lv_label_set_text(s_motor_text, buf);

        if (st.target_detected) {
            snprintf(buf, sizeof(buf), "LOCK (%d,%d)", st.local_target_x, st.local_target_y);
        } else {
            snprintf(buf, sizeof(buf), "SEARCH");
        }
        if (changed(4, buf)) lv_label_set_text(s_target_text, buf);

        if (st.estimated_dist_m >= 998.0f) {
            snprintf(buf, sizeof(buf), "--");
        } else {
            snprintf(buf, sizeof(buf), "%.2fm", st.estimated_dist_m);
        }
        if (changed(5, buf)) lv_label_set_text(s_dist_text, buf);

        /* 状态点：应急=红，正常=绿。
           必须带变化判断 —— 无条件调 lv_obj_set_style_* 会走对象失效流程，
           每帧都触发重绘。 */
        uint32_t dot = st.emergency_mode ? COL_BAD : COL_OK;
        if (dot != s_dot_color_cached) {
            s_dot_color_cached = dot;
            lv_obj_set_style_bg_color(s_link_dot, lv_color_hex(dot), 0);
        }
    } else {
        if (changed(3, "--")) lv_label_set_text(s_motor_text, "--");
        if (changed(4, "--")) lv_label_set_text(s_target_text, "--");
        if (changed(5, "--")) lv_label_set_text(s_dist_text, "--");
    }

    /* ---- 诊断行：芯片结温 / CPU 占用 ----
       显示在屏上而非只打日志：这块板的 USB 串口读取不稳定，
       直接看屏是排查发烫最可靠的手段。每 2 秒刷新一次即可。 */
    float celsius = 0.0f;
    if (diag_get_temperature(&celsius)) {
        snprintf(buf, sizeof(buf), "%.1f C", celsius);
    } else {
        snprintf(buf, sizeof(buf), "n/a");
    }
    if (changed_at_most_every(6, buf, 2000)) lv_label_set_text(s_temp_text, buf);

    uint32_t cpu0 = 0, cpu1 = 0;
    if (diag_get_cpu_load(&cpu0, &cpu1)) {
        /* 卡片只有 112 px 宽，用最紧凑写法避免被截断 */
        snprintf(buf, sizeof(buf), "%lu/%lu%%", (unsigned long)cpu0, (unsigned long)cpu1);
    } else {
        snprintf(buf, sizeof(buf), "--");
    }
    if (changed_at_most_every(7, buf, 2000)) lv_label_set_text(s_cpu_text, buf);
}
