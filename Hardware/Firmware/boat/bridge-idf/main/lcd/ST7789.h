/**
 * ST7789T 面板装配（SPI3_HOST）—— Waveshare ESP32-S3-LCD-1.47
 *
 * 本文件复用自 ESP32-S3-LCD-1.47-Demo 工程中已在实机验证过的配置：
 *   - 像素时钟 50 MHz（实测画面正常，整屏 320x172 传输约 17.6 ms）
 *   - 横屏 320x172：swap_xy + 偏移从 X 轴移到 Y 轴
 *
 * 面板原生 GRAM 为 240x320，可见窗口 172 列，两侧各空 34 列：
 *     竖屏 -> Offset_X = 34, Offset_Y = 0
 *     横屏 -> Offset_X = 0,  Offset_Y = 34   （X/Y 交换后偏移跟着换轴）
 * (240 - 172) / 2 = 34，这个数字不是魔数。
 */
#pragma once

#include <stdio.h>

#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "esp_err.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "Vernon_ST7789T.h"

/* 使用 SPI3_HOST */
#define LCD_HOST  SPI3_HOST

/* 像素时钟：本项目是状态仪表盘，用 20 MHz 而非 LCD Demo 里追求的 50 MHz。
 *
 * 为什么主动降速：
 *   - 屏幕内容按秒变化，20 MHz 下整屏 320x172 传输约 44 ms，远超 4 Hz 需求
 *   - SPI 时钟是实打实的动态功耗来源，长期开着的高频翻转会让板子发热
 *   - 50 MHz 是为"流畅动画"服务的；这里没有动画，降下来没有任何损失
 * 若日后要做动画，可逐步调回（12/20/30/40/50 MHz 均实测无 watchdog）。 */
#define EXAMPLE_LCD_PIXEL_CLOCK_HZ     (20 * 1000 * 1000)

#define EXAMPLE_PIN_NUM_SCLK           40
#define EXAMPLE_PIN_NUM_MOSI           45
#define EXAMPLE_PIN_NUM_MISO           -1
#define EXAMPLE_PIN_NUM_LCD_DC         41
#define EXAMPLE_PIN_NUM_LCD_RST        39
#define EXAMPLE_PIN_NUM_LCD_CS         42
#define EXAMPLE_PIN_NUM_BK_LIGHT       48

/* 横屏分辨率 */
#define EXAMPLE_LCD_H_RES              320
#define EXAMPLE_LCD_V_RES              172
#define Offset_X                       0
#define Offset_Y                       34

#define EXAMPLE_LCD_CMD_BITS           8
#define EXAMPLE_LCD_PARAM_BITS         8

/* 背光 LEDC */
#define LEDC_HS_TIMER          LEDC_TIMER_0
#define LEDC_LS_MODE           LEDC_LOW_SPEED_MODE
#define LEDC_HS_CH0_CHANNEL    LEDC_CHANNEL_0
#define LEDC_ResolutionRatio   LEDC_TIMER_13_BIT
#define LEDC_MAX_Duty          ((1 << LEDC_ResolutionRatio) - 1)

extern esp_lcd_panel_handle_t panel_handle;

void LCD_Init(void);
void BK_Init(void);
/** @brief 设置背光亮度 0-100 */
void BK_Light(uint8_t Light);
