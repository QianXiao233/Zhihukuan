/**
 * 桥接板固件 —— Waveshare ESP32-S3-LCD-1.47
 *
 * 职责（与 Arduino 版 controller.ino 行为一致，另外加上状态屏）：
 *   1. 解析电脑通过 USB 串口发来的 29 字节命令帧
 *   2. 以 20 Hz 把命令经 ESP-NOW 转发给船载 DFR1063（电脑静默时归零保活）
 *   3. 接收船端 32 字节状态帧，按 35 字节帧写回电脑
 *   4. 在 320x172 屏幕上显示串口链路 / ESP-NOW 链路 / 船端遥测
 *
 * 所有 LVGL 调用都集中在主任务里（创建、刷新、lv_timer_handler），
 * 因为 LVGL 不是线程安全的。
 */
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "comm/espnow_bridge.h"
#include "diag.h"
#include "lcd/LVGL_Driver.h"
#include "lcd/ST7789.h"
#include "lcd/ui_status.h"
#include "protocol/serial_protocol.h"

static const char *TAG = "BRIDGE_MAIN";

/* UI 刷新周期。
 *
 * 这是一个状态仪表盘，数据按秒变化；10 Hz 刷新没有视觉收益，却让 SPI 持续
 * 传输、芯片持续发热。250 ms（4 Hz）视觉上依然即时，重绘请求降到原来的 1/2.5。
 * 配合 ui_status.c 里的按秒节流，实际重绘次数更低。 */
#define UI_REFRESH_MS   250
/* 主循环周期：保持 20 Hz。
   注意：不要为了"更流畅"把它降到 5 ms —— Demo 工程实测过，
   5 ms 主循环叠加高频像素时钟会让 IDLE0 饿死并触发 task watchdog。 */
#define MAIN_LOOP_MS    20

/**
 * 诊断开关：置 1 则不启动 WiFi / ESP-NOW（屏幕与其余逻辑照常运行）。
 *
 * 用途：一次实验就能定位"芯片发烫"的热源归属 ——
 *   置 1 烧录后看屏幕 TEMP C：
 *     温度大幅下降  -> 射频是主因，继续往省电方向调
 *     温度几乎不变  -> 主因是 LDO/供电，固件改不了
 * 测完记得改回 0。置 1 时桥接功能不可用（船端会因收不到数据进应急模式，
 * 所以测试时船应断电或架空）。
 */
#define DIAG_DISABLE_RADIO   0

void app_main(void)
{
    ESP_LOGI(TAG, "桥接板启动（ESP32-S3-LCD-1.47 / ESP-IDF）");

    /* 0. 诊断：芯片温度 + CPU 占用，用于排查发烫问题 */
    diag_init();

    /* 1. 串口协议（USB-Serial-JTAG），需要最先起来以便尽早看到电脑命令 */
    serial_protocol_start();

    /* 2. 屏幕 + LVGL */
    LCD_Init();
    LVGL_Init();
    ui_status_create();

#if DIAG_DISABLE_RADIO
    /* 诊断模式：不启动射频，用于隔离"发热来自射频还是供电"。
       屏幕与诊断读数照常工作。 */
    ESP_LOGW(TAG, "*** 诊断模式：射频已禁用，桥接功能不可用 ***");
#else
    /* 3. ESP-NOW（必须在屏幕之后：屏幕初始化里打印自身 MAC 需要 Wi-Fi 已就绪，
          而 ui_status_create 也会读取 MAC 字符串） */
    espnow_bridge_start();

    ESP_LOGI(TAG, "本板 MAC: %s  船端 MAC: %s",
             espnow_bridge_own_mac_str(), espnow_bridge_peer_mac_str());
    ESP_LOGI(TAG, "等待电脑指令...");
#endif

    uint32_t last_ui_ms = 0;

    while (1) {
#if !DIAG_DISABLE_RADIO
        /* 取电脑命令（内部已应用 300 ms 超时归零）并发往船端（内部限频） */
        ground_to_boat_t command;
        serial_protocol_get_command(&command);
        espnow_bridge_send_command(&command);

        /* 收到船端状态就立刻回传电脑 */
        boat_to_ground_t status;
        if (espnow_bridge_get_status(&status)) {
            serial_protocol_send_status(&status);
        }
#endif

        /* 周期性刷新屏幕 */
        uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
        if (now - last_ui_ms >= UI_REFRESH_MS) {
            last_ui_ms = now;
            ui_status_update();
        }

        /* LVGL 计时器处理 + 让出 CPU */
        lv_timer_handler();

        /* 每 5 秒输出一次芯片结温与 CPU 占用（排查发烫） */
        diag_tick();

        vTaskDelay(pdMS_TO_TICKS(MAIN_LOOP_MS));
    }
}
