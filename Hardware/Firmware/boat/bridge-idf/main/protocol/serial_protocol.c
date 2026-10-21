/**
 * 串口协议实现（电脑 <-> 桥接板）
 *
 * 说明：ESP32-S3 的原生 USB 是 USB-Serial-JTAG。这里用专用驱动
 * (usb_serial_jtag_driver_install) 收发协议帧，同时保留 ROM 控制台用于日志。
 * 两者共用同一个 USB 端点，但驱动读走协议数据、日志走 stdout，互不干扰。
 */
#include "serial_protocol.h"

#include <string.h>

#include "driver/usb_serial_jtag.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"

static const char *TAG = "BRIDGE_PROTO";

/* 接收状态机 */
typedef enum {
    RX_WAIT_HEADER_0 = 0,
    RX_WAIT_HEADER_1,
    RX_PAYLOAD,
    RX_CHECKSUM,
} rx_state_t;

typedef struct {
    rx_state_t state;
    uint8_t payload[sizeof(ground_to_boat_t)];
    size_t index;
    uint8_t checksum;
} inbox_t;

static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;

static ground_to_boat_t s_command;              /* 当前待发命令（已应用超时归零） */
static ground_to_boat_t s_last_received;        /* 最后一次收到的原始命令 */
static uint32_t s_last_command_ms;              /* 上次收到有效命令的时刻 */
static uint32_t s_command_count;
static bool s_host_seen;

static inbox_t s_rx;                            /* 接收状态机现场 */

static void apply_byte(uint8_t value)
{
    switch (s_rx.state) {
    case RX_WAIT_HEADER_0:
        if (value == CMD_HEADER_0) s_rx.state = RX_WAIT_HEADER_1;
        break;

    case RX_WAIT_HEADER_1:
        if (value == CMD_HEADER_1) {
            s_rx.index = 0;
            s_rx.checksum = 0;
            s_rx.state = RX_PAYLOAD;
        } else {
            /* 允许 A5 A5 5A 这类重叠序列 */
            s_rx.state = (value == CMD_HEADER_0) ? RX_WAIT_HEADER_1 : RX_WAIT_HEADER_0;
        }
        break;

    case RX_PAYLOAD:
        s_rx.payload[s_rx.index++] = value;
        s_rx.checksum += value;
        if (s_rx.index == sizeof(s_rx.payload)) s_rx.state = RX_CHECKSUM;
        break;

    case RX_CHECKSUM:
        if (value == s_rx.checksum) {
            portENTER_CRITICAL(&s_lock);
            memcpy(&s_last_received, s_rx.payload, sizeof(s_last_received));
            s_last_command_ms = xTaskGetTickCount() * portTICK_PERIOD_MS;
            s_command_count++;
            s_host_seen = true;
            portEXIT_CRITICAL(&s_lock);
        } else {
            ESP_LOGW(TAG, "校验失败: 收到 0x%02X 期望 0x%02X", value, s_rx.checksum);
        }
        s_rx.state = RX_WAIT_HEADER_0;
        break;
    }
}

static void serial_rx_task(void *arg)
{
    (void)arg;
    uint8_t buf[64];

    while (1) {
        int n = usb_serial_jtag_read_bytes(buf, sizeof(buf), pdMS_TO_TICKS(20));
        for (int i = 0; i < n; i++) apply_byte(buf[i]);
    }
}

void serial_protocol_start(void)
{
    usb_serial_jtag_driver_config_t cfg = {
        .tx_buffer_size = 1024,
        .rx_buffer_size = 1024,
    };
    ESP_ERROR_CHECK(usb_serial_jtag_driver_install(&cfg));

    memset(&s_command, 0, sizeof(s_command));
    memset(&s_last_received, 0, sizeof(s_last_received));
    s_rx.state = RX_WAIT_HEADER_0;

    xTaskCreate(serial_rx_task, "serial_rx", 3072, NULL, 10, NULL);
}

void serial_protocol_get_command(ground_to_boat_t *out)
{
    portENTER_CRITICAL(&s_lock);
    uint32_t last = s_last_command_ms;
    bool seen = s_host_seen;
    ground_to_boat_t snapshot = s_last_received;
    portEXIT_CRITICAL(&s_lock);

    if (!seen) {
        memset(out, 0, sizeof(*out));
        return;
    }

    uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
    bool fresh = (now - last) <= HOST_COMMAND_TIMEOUT_MS;

    *out = snapshot;
    if (!fresh) {
        /* 电脑静默：保留链路但把动作归零，避免船继续执行过期指令 */
        out->mission_state = 0;
        out->release_flag = 0;
        out->manual_throttle = 0;
        out->manual_steer = 0;
    }
}

bool serial_protocol_host_alive(void)
{
    portENTER_CRITICAL(&s_lock);
    bool seen = s_host_seen;
    uint32_t last = s_last_command_ms;
    portEXIT_CRITICAL(&s_lock);
    if (!seen) return false;
    uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
    return (now - last) <= HOST_COMMAND_TIMEOUT_MS;
}

uint32_t serial_protocol_host_silence_ms(void)
{
    portENTER_CRITICAL(&s_lock);
    bool seen = s_host_seen;
    uint32_t last = s_last_command_ms;
    portEXIT_CRITICAL(&s_lock);
    if (!seen) return UINT32_MAX;
    return xTaskGetTickCount() * portTICK_PERIOD_MS - last;
}

uint32_t serial_protocol_command_count(void)
{
    portENTER_CRITICAL(&s_lock);
    uint32_t count = s_command_count;
    portEXIT_CRITICAL(&s_lock);
    return count;
}

void serial_protocol_send_status(const boat_to_ground_t *status)
{
    uint8_t frame[2 + sizeof(boat_to_ground_t) + 1];
    frame[0] = STATUS_HEADER_0;
    frame[1] = STATUS_HEADER_1;
    memcpy(&frame[2], status, sizeof(*status));

    uint8_t checksum = 0;
    for (size_t i = 0; i < sizeof(*status); i++) checksum += frame[2 + i];
    frame[sizeof(frame) - 1] = checksum;

    usb_serial_jtag_write_bytes(frame, sizeof(frame), pdMS_TO_TICKS(20));
}
