/**
 * LVGL 移植层实现
 */
#include "LVGL_Driver.h"

static const char *TAG_LVGL = "BRIDGE_LVGL";

/* 双缓冲：数组长度与 lv_disp_draw_buf_init 的尺寸参数严格一致 */
static lv_color_t s_buf1[LVGL_BUF_LEN];
static lv_color_t s_buf2[LVGL_BUF_LEN];

lv_disp_draw_buf_t disp_buf;
lv_disp_drv_t disp_drv;

void example_increase_lvgl_tick(void *arg)
{
    (void)arg;
    lv_tick_inc(EXAMPLE_LVGL_TICK_PERIOD_MS);
}

bool example_notify_lvgl_flush_ready(esp_lcd_panel_io_handle_t panel_io,
                                     esp_lcd_panel_io_event_data_t *edata,
                                     void *user_ctx)
{
    (void)panel_io;
    (void)edata;
    lv_disp_drv_t *driver = (lv_disp_drv_t *)user_ctx;
    lv_disp_flush_ready(driver);
    return false;
}

void example_lvgl_flush_cb(lv_disp_drv_t *drv, const lv_area_t *area, lv_color_t *color_map)
{
    esp_lcd_panel_handle_t panel = (esp_lcd_panel_handle_t)drv->user_data;

    /* 面板 GRAM 比可见区宽 34 像素，需要平移。
       注意 LVGL 的 x2/y2 是闭区间，esp_lcd 的 end 是开区间，所以要 +1。 */
    esp_lcd_panel_draw_bitmap(panel,
                              area->x1 + Offset_X,
                              area->y1 + Offset_Y,
                              area->x2 + Offset_X + 1,
                              area->y2 + Offset_Y + 1,
                              color_map);
    /* 不在这里调用 lv_disp_flush_ready()：由 DMA 完成回调负责，
       这样 LVGL 可以立刻用另一个缓冲继续绘制，不必阻塞等 SPI 传完。 */
}

void LVGL_Init(void)
{
    ESP_LOGI(TAG_LVGL, "初始化 LVGL");
    lv_init();

    lv_disp_draw_buf_init(&disp_buf, s_buf1, s_buf2, LVGL_BUF_LEN);

    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = EXAMPLE_LCD_H_RES;
    disp_drv.ver_res = EXAMPLE_LCD_V_RES;
    disp_drv.flush_cb = example_lvgl_flush_cb;
    disp_drv.draw_buf = &disp_buf;
    disp_drv.user_data = panel_handle;
    lv_disp_drv_register(&disp_drv);

    const esp_timer_create_args_t tick_args = {
        .callback = &example_increase_lvgl_tick,
        .name = "lvgl_tick",
    };
    esp_timer_handle_t tick_timer = NULL;
    ESP_ERROR_CHECK(esp_timer_create(&tick_args, &tick_timer));
    ESP_ERROR_CHECK(esp_timer_start_periodic(tick_timer, EXAMPLE_LVGL_TICK_PERIOD_MS * 1000));

    ESP_LOGI(TAG_LVGL, "LVGL 就绪 (%dx%d, 缓冲 %d px)", EXAMPLE_LCD_H_RES, EXAMPLE_LCD_V_RES, LVGL_BUF_LEN);
}
