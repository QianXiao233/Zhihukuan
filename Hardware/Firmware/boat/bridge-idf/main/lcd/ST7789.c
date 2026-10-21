/**
 * ST7789T 面板装配实现（复用自已验证的 Demo 工程配置）
 */
#include "ST7789.h"

#include "LVGL_Driver.h"   /* example_notify_lvgl_flush_ready / disp_drv */

static const char *TAG_LCD = "BRIDGE_LCD";

esp_lcd_panel_handle_t panel_handle = NULL;

void LCD_Init(void)
{
    ESP_LOGI(TAG_LCD, "初始化 SPI 总线");
    spi_bus_config_t buscfg = {
        .sclk_io_num = EXAMPLE_PIN_NUM_SCLK,
        .mosi_io_num = EXAMPLE_PIN_NUM_MOSI,
        .miso_io_num = EXAMPLE_PIN_NUM_MISO,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = EXAMPLE_LCD_H_RES * EXAMPLE_LCD_V_RES * sizeof(uint16_t),
    };
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    ESP_LOGI(TAG_LCD, "安装 panel IO");
    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = EXAMPLE_PIN_NUM_LCD_DC,
        .cs_gpio_num = EXAMPLE_PIN_NUM_LCD_CS,
        .pclk_hz = EXAMPLE_LCD_PIXEL_CLOCK_HZ,
        .lcd_cmd_bits = EXAMPLE_LCD_CMD_BITS,
        .lcd_param_bits = EXAMPLE_LCD_PARAM_BITS,
        .spi_mode = 0,
        .trans_queue_depth = 10,
        /* DMA 发送完成回调：直接通知 LVGL，避免阻塞等待 */
        .on_color_trans_done = example_notify_lvgl_flush_ready,
        .user_ctx = &disp_drv,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_config, &io_handle));

    esp_lcd_panel_dev_st7789t_config_t panel_config = {
        .reset_gpio_num = EXAMPLE_PIN_NUM_LCD_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_BGR,
        .bits_per_pixel = 16,
    };
    ESP_LOGI(TAG_LCD, "安装 ST7789T 面板驱动");
    ESP_ERROR_CHECK(esp_lcd_new_panel_st7789t(io_handle, &panel_config, &panel_handle));

    ESP_ERROR_CHECK(esp_lcd_panel_reset(panel_handle));
    ESP_ERROR_CHECK(esp_lcd_panel_init(panel_handle));

    /* 横屏 320x172。
       注意：drv_update_cb 只在运行时改变方向时被调用，lv_disp_drv_register()
       期间不会调用。所以初始 MADCTL 必须在这里设置，否则第一帧方向就是错的。 */
    ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(panel_handle, true));
    ESP_ERROR_CHECK(esp_lcd_panel_mirror(panel_handle, true, true));

    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(panel_handle, true));

    BK_Init();
    /* 背光 60%：背光是这块板最持续、最直接的发热源，亮度与电流近似线性。
       60% 在室内看仍然清楚，却把背光电流降到原来的约 60%。
       偏暗可调回 75；若仍然烫，优先降到 40 再试。 */
    BK_Light(60);
    ESP_LOGI(TAG_LCD, "屏幕初始化完成");
}

/* ---------------- 背光 ---------------- */
static ledc_channel_config_t s_ledc_channel;

void BK_Init(void)
{
    gpio_config_t bk_gpio_config = {
        .mode = GPIO_MODE_OUTPUT,
        .pin_bit_mask = 1ULL << EXAMPLE_PIN_NUM_BK_LIGHT,
    };
    ESP_ERROR_CHECK(gpio_config(&bk_gpio_config));

    ledc_timer_config_t ledc_timer = {
        .duty_resolution = LEDC_TIMER_13_BIT,
        .freq_hz = 5000,
        .speed_mode = LEDC_LS_MODE,
        .timer_num = LEDC_HS_TIMER,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ledc_timer_config(&ledc_timer);

    s_ledc_channel.channel    = LEDC_HS_CH0_CHANNEL;
    s_ledc_channel.duty       = 0;
    s_ledc_channel.gpio_num   = EXAMPLE_PIN_NUM_BK_LIGHT;
    s_ledc_channel.speed_mode = LEDC_LS_MODE;
    s_ledc_channel.timer_sel  = LEDC_HS_TIMER;
    ledc_channel_config(&s_ledc_channel);
    ledc_fade_func_install(0);

    /* 说明：GPIO48 是 Octal PSRAM 的 CS1 引脚，会被 esp_psram 登记占用，
       ledc 会打印 "GPIO 48 is not usable, maybe conflict with others"。
       该告警非致命：LEDC 只是提示引脚已被登记，仍会完成信号路由并返回成功，
       背光受控。本项目未启用 PSRAM，该告警也不会出现。 */
}

void BK_Light(uint8_t Light)
{
    if (Light > 100) Light = 100;
    uint16_t Duty = LEDC_MAX_Duty - (81 * (100 - Light));
    if (Light == 0) Duty = 0;
    ledc_set_duty(s_ledc_channel.speed_mode, s_ledc_channel.channel, Duty);
    ledc_update_duty(s_ledc_channel.speed_mode, s_ledc_channel.channel);
}
