/**
 * ESP-NOW 桥接层实现
 */
#include "espnow_bridge.h"

#include <stdio.h>
#include <string.h>

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

/* 两个固件共用的硬件地址定义（本文件转发 arduino-reference/boat_config.h） */
#include "bridge_config.h"

static const char *TAG = "BRIDGE_ESPNOW";

/* 发送限频：船端主循环 20 Hz，桥接板按 50 ms 发一次即可 */
/**
 * 发送间隔（毫秒）。
 *
 * 实测结论（这一版固件做过的关键实验）：
 *   射频关闭 -> 芯片结温 34.4 °C
 *   射频开启 -> 芯片结温 78 °C
 *   两者差 ≈ 44 °C —— 说明发热几乎全部来自射频，与屏幕/LDO/CPU 基本无关。
 *   因此降温的唯一有效手段就是降低射频的开销。
 *
 * 从 50 ms（20 帧/秒）降到 200 ms（5 帧/秒）已实测"温度没怎么降"，
 * 说明主要成本是"射频打开"本身（PLL 与模拟前端的固有开销），
 * 而不是单次发射次数。继续降频率收益有限，但仍可减少脉冲部分。
 *
 * 安全约束：船端 3 秒收不到数据就进应急模式。
 * 500 ms（2 帧/秒）仍有 6 倍安全余量，链路中断判定依然及时。
 */
#define SEND_INTERVAL_MS 500

/**
 * 射频发射功率（单位 0.25 dBm，范围 8~84，即 2~20 dBm）。
 * 40 = 10 dBm。船距离桥接板只有 1~2 米，远不需要默认的 20 dBm（100 mW）；
 * 发射功率与功放耗电近似线性，降到 10 dBm 能显著减少发热。
 * 若现场距离远或丢包，逐步往上调（如 52 = 13 dBm、64 = 16 dBm）。
 */
#define ESPNOW_TX_POWER_QUARTER_DBM 40

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

static boat_to_ground_t s_status;
static bool s_status_valid;
static uint32_t s_last_rx_ms;

static bool s_last_send_ok;
static uint32_t s_sent_count;
static uint32_t s_recv_count;
static uint32_t s_send_fail_count;
static uint32_t s_last_send_ms;

static uint8_t s_own_mac[6];
static char s_own_mac_str[18];
static char s_peer_mac_str[18];

static void mac_to_str(const uint8_t *mac, char *out)
{
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static uint32_t now_ms(void)
{
    return xTaskGetTickCount() * portTICK_PERIOD_MS;
}

/* ---- 发送完成回调：判断链路是否真的通 ---- */
static void on_send_done(const esp_now_send_info_t *tx_info, esp_now_send_status_t status)
{
    (void)tx_info;
    portENTER_CRITICAL(&s_lock);
    s_last_send_ok = (status == ESP_NOW_SEND_SUCCESS);
    if (s_last_send_ok) {
        s_sent_count++;
        s_last_send_ms = now_ms();
    } else {
        s_send_fail_count++;
    }
    portEXIT_CRITICAL(&s_lock);
}

/* ---- 接收回调：船端状态帧 ---- */
static void on_recv(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    if (info == NULL || data == NULL) return;
    /* 只接受白名单 MAC，且长度必须精确匹配 */
    if (memcmp(info->src_addr, BOAT_CONTROLLER_MAC, 6) != 0) return;
    if (len != (int)sizeof(boat_to_ground_t)) return;

    portENTER_CRITICAL(&s_lock);
    memcpy(&s_status, data, sizeof(s_status));
    s_status_valid = true;
    s_last_rx_ms = now_ms();
    s_recv_count++;
    portEXIT_CRITICAL(&s_lock);
}

void espnow_bridge_start(void)
{
    /* NVS 是 Wi-Fi 驱动的前提 */
    esp_err_t nvs = nvs_flash_init();
    if (nvs == ESP_ERR_NVS_NO_FREE_PAGES || nvs == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs);

    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());

    wifi_init_config_t wifi_cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&wifi_cfg));
    ESP_ERROR_CHECK(esp_wifi_set_storage(WIFI_STORAGE_RAM));
    /* 注意是 WIFI_MODE_STA（ESP-IDF 枚举）；Arduino 里的 WIFI_STA 是另一个枚举名 */
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());

    /* 降低发射功率以减少发热。
       注意：必须在 esp_wifi_start() **之后**调用 —— 文档明确写了
       start 之前调用会返回 ESP_ERR_WIFI_NOT_STARTED。
       （第一版就是放在 start 之前，导致设置静默失效、温度没降。） */
    esp_err_t tx_err = esp_wifi_set_max_tx_power(ESPNOW_TX_POWER_QUARTER_DBM);
    if (tx_err != ESP_OK) {
        ESP_LOGW(TAG, "设置发射功率失败: %s（继续使用默认功率）", esp_err_to_name(tx_err));
    } else {
        int8_t actual = 0;
        if (esp_wifi_get_max_tx_power(&actual) == ESP_OK) {
            ESP_LOGI(TAG, "发射功率已设置: 请求 %d (%.1f dBm) 实际 %d (%.1f dBm)",
                     ESPNOW_TX_POWER_QUARTER_DBM, ESPNOW_TX_POWER_QUARTER_DBM * 0.25,
                     actual, actual * 0.25);
        }
    }

    /* 两端必须锁在同一个信道，并读回校验 */
    ESP_ERROR_CHECK(esp_wifi_set_channel(BOAT_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE));
    uint8_t primary = 0;
    wifi_second_chan_t secondary = WIFI_SECOND_CHAN_NONE;
    ESP_ERROR_CHECK(esp_wifi_get_channel(&primary, &secondary));
    if (primary != BOAT_WIFI_CHANNEL) {
        ESP_LOGE(TAG, "信道设置失败: 期望 %u 实际 %u", BOAT_WIFI_CHANNEL, primary);
    }

    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_send_cb(on_send_done));
    ESP_ERROR_CHECK(esp_now_register_recv_cb(on_recv));

    esp_now_peer_info_t peer = {0};
    memcpy(peer.peer_addr, BOAT_CONTROLLER_MAC, 6);
    peer.channel = BOAT_WIFI_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));

    ESP_ERROR_CHECK(esp_read_mac(s_own_mac, ESP_MAC_WIFI_STA));
    mac_to_str(s_own_mac, s_own_mac_str);
    mac_to_str(BOAT_CONTROLLER_MAC, s_peer_mac_str);

    ESP_LOGI(TAG, "桥接板 MAC: %s", s_own_mac_str);
    ESP_LOGI(TAG, "目标船载 MAC: %s", s_peer_mac_str);
    ESP_LOGI(TAG, "信道: %u, ESP-NOW 初始化完成", primary);
}

void espnow_bridge_send_command(const ground_to_boat_t *command)
{
    if (command == NULL) return;

    uint32_t t = now_ms();
    if (t - s_last_send_ms < SEND_INTERVAL_MS) return;

    esp_now_send(BOAT_CONTROLLER_MAC, (const uint8_t *)command, sizeof(*command));
}

bool espnow_bridge_get_status(boat_to_ground_t *out)
{
    if (out == NULL) return false;
    portENTER_CRITICAL(&s_lock);
    bool valid = s_status_valid;
    if (valid) memcpy(out, &s_status, sizeof(*out));
    portEXIT_CRITICAL(&s_lock);
    return valid;
}

uint32_t espnow_bridge_boat_silence_ms(void)
{
    portENTER_CRITICAL(&s_lock);
    bool valid = s_status_valid;
    uint32_t last = s_last_rx_ms;
    portEXIT_CRITICAL(&s_lock);
    if (!valid) return UINT32_MAX;
    return now_ms() - last;
}

bool espnow_bridge_last_send_ok(void)
{
    portENTER_CRITICAL(&s_lock);
    bool ok = s_last_send_ok;
    portEXIT_CRITICAL(&s_lock);
    return ok;
}

void espnow_bridge_counters(uint32_t *sent, uint32_t *received, uint32_t *send_fail)
{
    portENTER_CRITICAL(&s_lock);
    if (sent) *sent = s_sent_count;
    if (received) *received = s_recv_count;
    if (send_fail) *send_fail = s_send_fail_count;
    portEXIT_CRITICAL(&s_lock);
}

const char *espnow_bridge_own_mac_str(void)  { return s_own_mac_str; }
const char *espnow_bridge_peer_mac_str(void) { return s_peer_mac_str; }
