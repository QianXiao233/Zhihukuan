/**
 * LVGL 移植层 —— 显示驱动注册、绘制缓冲、时基
 */
#pragma once

#include "esp_err.h"
#include "esp_lcd_panel_io.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "lvgl.h"

#include "ST7789.h"

/**
 * 绘制缓冲长度（单位：像素）。
 * 取整屏的 1/10 左右，192*20 与 Demo 工程同量级，双缓冲共约 27 KB。
 * 重要：这个宏同时用于**数组分配**和 lv_disp_draw_buf_init() 的尺寸参数，
 * 两者必须完全一致，否则 LVGL 会越界写堆（Demo 工程踩过这个坑，会崩）。
 */
#define LVGL_BUF_LEN   (EXAMPLE_LCD_H_RES * 20)

#define EXAMPLE_LVGL_TICK_PERIOD_MS   2

extern lv_disp_draw_buf_t disp_buf;
extern lv_disp_drv_t disp_drv;

/** @brief 面板 DMA 发送完成回调，通知 LVGL 可以复用缓冲 */
bool example_notify_lvgl_flush_ready(esp_lcd_panel_io_handle_t panel_io,
                                     esp_lcd_panel_io_event_data_t *edata,
                                     void *user_ctx);

/** @brief LVGL 刷新回调：把脏区域交给面板 */
void example_lvgl_flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map);

/** @brief 时基回调 */
void example_increase_lvgl_tick(void *arg);

/** @brief 初始化 LVGL 并注册显示驱动 */
void LVGL_Init(void);
