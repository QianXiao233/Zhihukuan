/**
 * ESP-NOW 链路实现（船载侧）
 */
#include "espnow_link.h"

#include <stdio.h>
#include <string.h>

#include "shared/boat_controller_config.h"

#include "esp_event.h"
#include "esp_log.h"
#include "esp_mac.h"
#include "esp_now.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"

static const char *TAG = "BOAT_LINK";

#define SEND_INTERVAL_MS 50   /* 20 Hz 上报 */

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

static ground_to_boat_t s_pending;
static volatile bool s_pending_ready;
static volatile bool s_ever_seen;
static uint32_t s_last_rx_ms;
static uint32_t s_recv_count;
static uint32_t s_send_fail_count;
static uint32_t s_last_send_ms;

static char s_own_mac_str[18];
static char s_bridge_mac_str[18];

static void mac_to_str(const uint8_t *mac, char *out)
{
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
             mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

static uint32_t now_ms(void)
{
    return xTaskGetTickCount() * portTICK_PERIOD_MS;
}

/* 接收回调：只接受白名单 MAC + 精确长度。中断上下文，尽量少做事。 */
static void on_recv(const esp_now_recv_info_t *info, const uint8_t *data, int len)
{
    if (info == NULL || data == NULL) return;
    if (memcmp(info->src_addr, BOAT_BRIDGE_MAC, 6) != 0) return;
    if (len != (int)sizeof(ground_to_boat_t)) return;

    portENTER_CRITICAL(&s_lock);
    memcpy(&s_pending, data, sizeof(s_pending));
    s_pending_ready = true;
    s_ever_seen = true;
    s_last_rx_ms = now_ms();
    s_recv_count++;
    portEXIT_CRITICAL(&s_lock);
}

static void on_send_done(const esp_now_send_info_t *tx_info, esp_now_send_status_t status)
{
    (void)tx_info;
    if (status != ESP_NOW_SEND_SUCCESS) {
        portENTER_CRITICAL(&s_lock);
        s_send_fail_count++;
        portEXIT_CRITICAL(&s_lock);
    }
}

void espnow_link_start(void)
{
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
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_start());

    /* 两端必须锁在同一信道，并读回校验 */
    ESP_ERROR_CHECK(esp_wifi_set_channel(BOAT_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE));
    uint8_t primary = 0;
    wifi_second_chan_t secondary = WIFI_SECOND_CHAN_NONE;
    ESP_ERROR_CHECK(esp_wifi_get_channel(&primary, &secondary));
    if (primary != BOAT_WIFI_CHANNEL) {
        ESP_LOGE(TAG, "信道设置失败: 期望 %u 实际 %u", BOAT_WIFI_CHANNEL, primary);
    }

    ESP_ERROR_CHECK(esp_now_init());
    ESP_ERROR_CHECK(esp_now_register_recv_cb(on_recv));
    ESP_ERROR_CHECK(esp_now_register_send_cb(on_send_done));

    esp_now_peer_info_t peer = {0};
    memcpy(peer.peer_addr, BOAT_BRIDGE_MAC, 6);
    peer.channel = BOAT_WIFI_CHANNEL;
    peer.ifidx = WIFI_IF_STA;
    peer.encrypt = false;
    ESP_ERROR_CHECK(esp_now_add_peer(&peer));

    uint8_t own[6] = {0};
    ESP_ERROR_CHECK(esp_read_mac(own, ESP_MAC_WIFI_STA));
    mac_to_str(own, s_own_mac_str);
    mac_to_str(BOAT_BRIDGE_MAC, s_bridge_mac_str);

    ESP_LOGI(TAG, "船载 MAC: %s", s_own_mac_str);
    ESP_LOGI(TAG, "目标桥接板 MAC: %s", s_bridge_mac_str);
    ESP_LOGI(TAG, "信道: %u, ESP-NOW 初始化完成", primary);
}

bool espnow_link_take_command(ground_to_boat_t *out)
{
    if (out == NULL) return false;
    bool ready = false;
    portENTER_CRITICAL(&s_lock);
    if (s_pending_ready) {
        memcpy(out, &s_pending, sizeof(*out));
        s_pending_ready = false;
        ready = true;
    }
    portEXIT_CRITICAL(&s_lock);
    return ready;
}

uint32_t espnow_link_silence_ms(void)
{
    portENTER_CRITICAL(&s_lock);
    bool seen = s_ever_seen;
    uint32_t last = s_last_rx_ms;
    portEXIT_CRITICAL(&s_lock);
    if (!seen) return UINT32_MAX;
    return now_ms() - last;
}

bool espnow_link_ever_seen(void)
{
    portENTER_CRITICAL(&s_lock);
    bool seen = s_ever_seen;
    portEXIT_CRITICAL(&s_lock);
    return seen;
}

void espnow_link_send_status(const boat_to_ground_t *status)
{
    if (status == NULL) return;
    uint32_t t = now_ms();
    if (t - s_last_send_ms < SEND_INTERVAL_MS) return;
    s_last_send_ms = t;
    esp_now_send(BOAT_BRIDGE_MAC, (const uint8_t *)status, sizeof(*status));
}

void espnow_link_counters(uint32_t *recv, uint32_t *send_fail)
{
    portENTER_CRITICAL(&s_lock);
    if (recv) *recv = s_recv_count;
    if (send_fail) *send_fail = s_send_fail_count;
    portEXIT_CRITICAL(&s_lock);
}

const char *espnow_link_own_mac_str(void)    { return s_own_mac_str; }
const char *espnow_link_bridge_mac_str(void) { return s_bridge_mac_str; }
