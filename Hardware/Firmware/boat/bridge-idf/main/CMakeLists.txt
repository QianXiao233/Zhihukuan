idf_component_register(
    SRCS "main.c"
         "diag.c"
         "lcd/ST7789.c"
         "lcd/Vernon_ST7789T.c"
         "lcd/LVGL_Driver.c"
         "lcd/ui_status.c"
         "protocol/serial_protocol.c"
         "comm/espnow_bridge.c"

    INCLUDE_DIRS "."
                 "lcd"
                 "protocol"
                 "comm"

    # IDF 6.x 一旦显式声明依赖，main 就失去“隐式可见所有组件”的待遇，
    # 用到哪个组件的头文件就必须逐个列出（这是迁移时踩过的坑）
    REQUIRES esp_lcd
             esp_driver_spi
             esp_driver_gpio
             esp_driver_ledc
             esp_driver_usb_serial_jtag
             esp_driver_tsens
             esp_timer
             esp_wifi
             nvs_flash
             lvgl__lvgl
)
