idf_component_register(
    SRCS "main.c"
         "comm/espnow_link.c"
         "hw/motors.c"
         "hw/servo_release.c"
         "hw/huskylens.c"
         "control/navigation.c"

    INCLUDE_DIRS "."
                 "comm"
                 "hw"
                 "control"

    # IDF 6.x 显式声明依赖后，main 不再隐式可见所有组件
    REQUIRES esp_wifi
             esp_driver_gpio
             esp_driver_ledc
             esp_driver_i2c
             esp_timer
             nvs_flash
)

# 安全开关 ENABLE_MOTOR_OUTPUT 定义在 shared/boat_controller_config.h，
# 方便连同注释一起维护（idf_component_register 没有 PRIV_DEFINES 这个参数）。
