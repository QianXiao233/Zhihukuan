#include "mqtt_app.h"
#include "lwip/apps/mqtt.h"
#include "lwip/netif.h"
#include "lwip/ip_addr.h"
#include "lwip/dhcp.h"
#include "lwip/tcpip.h"
#include "main.h"
#include "usart.h"
#include "lcd_state.h"
#include "rtc_config.h"
#include "devices.h"
#include "sensor_task.h"
#include <string.h>
#include <stdio.h>

/* 命令队列：tcpip 线程 → MQTT 任务。
   注意：mqtt 回调里的 data 指针只在回调期间有效，必须复制后再入队。 */
#define CMD_QUEUE_LEN   4
#define CMD_MSG_MAX     192
typedef struct {
    uint16_t len;
    char     data[CMD_MSG_MAX];
} CmdMsg_t;
static osMessageQueueId_t g_cmd_queue = NULL;

/* 调试输出 */
#define DBG_PRINT(fmt, ...)                         \
  do {                                               \
    char _dbg_buf[128];                              \
    int _n = snprintf(_dbg_buf, sizeof(_dbg_buf),   \
                      "[MQTT] " fmt "\r\n", ##__VA_ARGS__); \
    extern UART_HandleTypeDef huart1;                \
    HAL_UART_Transmit(&huart1, (uint8_t*)_dbg_buf,  \
                      _n > 0 ? (_n < 128 ? _n : 128) : 0, \
                      100);                          \
  } while(0)

/* 话题定义 */
#define TOPIC_CONTROL   "rtu/control"
#define TOPIC_STATUS    "rtu/status"

/* ClientId 前缀：后面拼接 MCU 唯一 ID（见 mqtt_build_client_id）。
   避免多台设备/测试客户端使用同一 ClientId 时被 Broker 互相踢下线。 */
#define MQTT_CLIENT_ID_PREFIX   "rtu_"

/* keep-alive（秒） */
#define MQTT_KEEPALIVE_S        51

/* 重连等待（毫秒） */
#define RECONNECT_DELAY_MS      1000

/* 连续上报失败达到该次数就主动重连 */
#define PUB_FAIL_LIMIT          3

/* 连接超时（CONNECTING 状态最长停留时间） */
#define CONNECT_TIMEOUT_MS   10000

/* 上报间隔（毫秒）：1.5 秒。
   采集周期是 1000ms，1.5s 不是它的整数倍，因此上报按固定时间间隔触发，
   每次上报发送当前最新的采集值（可能重复上一批数据）。 */
#define PUBLISH_INTERVAL_MS   1500

/* 任务状态 */
enum {
    MQTT_STATE_WAIT_LWIP = 0,
    MQTT_STATE_CONNECT,
    MQTT_STATE_CONNECTING,  /* 等待异步连接回调 */
    MQTT_STATE_CONNECTED,
    MQTT_STATE_RECONNECT
};

static mqtt_client_t *g_mqtt_client = NULL;
static volatile int g_mqtt_state = MQTT_STATE_WAIT_LWIP;
static char g_broker_ip[16] = "0.0.0.0";  /* 当前 Broker IP 字符串 */
static uint16_t g_broker_port = 1883;      /* 当前 Broker 端口 */
static uint32_t g_last_publish_tick = 0;   /* 上次上报时刻（0=还没报过） */
static uint32_t g_connect_start_tick = 0;  /* 本次连接开始时刻 */
static volatile uint8_t g_subscribed = 0;  /* 本次连接是否已订阅 */
static int g_pub_fail = 0;                 /* 连续上报失败次数 */
static char g_client_id[24] = "rtu_00000000"; /* 唯一 ClientId */
static volatile int g_last_disc_reason = 0;   /* 最近一次断开原因 */
static volatile uint32_t g_disc_count = 0;    /* 断连/重连次数 */

/* 本地触发的断开原因码（>=1000，避免与 lwIP MQTT 状态码冲突） */
#define MQTT_DISC_LINK_DOWN      1000
#define MQTT_DISC_PUB_FAIL       1001
#define MQTT_DISC_CONN_TIMEOUT   1002

/* 用 MCU 唯一 ID 生成 MQTT ClientId（UART/网口多机同 ID 会被 Broker 互踢） */
static void mqtt_build_client_id(void)
{
    snprintf(g_client_id, sizeof(g_client_id), MQTT_CLIENT_ID_PREFIX "%08lX%06lX",
             (unsigned long)HAL_GetUIDw0(),
             (unsigned long)(HAL_GetUIDw1() & 0x00FFFFFFUL));
}

/* 供 LCD 任务读取当前 Broker，避免在 UI 任务里调用 RTC_LoadBrokerConfig() +
   sscanf（会额外吃掉几百字节栈，曾在 1KB 栈的 LCD 任务里引发栈溢出） */
void MQTT_GetBrokerInfo(char *ip, int ip_len, uint16_t *port)
{
    if (ip != NULL && ip_len > 1) {
        strncpy(ip, g_broker_ip, (size_t)ip_len - 1);
        ip[ip_len - 1] = '\0';
    }
    if (port != NULL) {
        *port = g_broker_port;
    }
}

void MQTT_GetStats(int *last_reason, uint32_t *disc_count)
{
    if (last_reason != NULL) {
        *last_reason = g_last_disc_reason;
    }
    if (disc_count != NULL) {
        *disc_count = g_disc_count;
    }
}

/* -------- JSON 解析（轻量，仅提取整数） ---------- */
static int json_get_int(const char *json, const char *key, int *value)
{
    const char *p = json, *key_pos;
    int key_len = strlen(key);
    while (*p) {
        if (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n'
            || *p == '{' || *p == '}' || *p == '[' || *p == ']' || *p == ',')
        { p++; continue; }
        if (*p == '\"' || *p == '\'') { p++; key_pos = p; }
        else { key_pos = p; }
        if (strncmp(key_pos, key, key_len) == 0) {
            const char *v = key_pos + key_len;
            while (*v && *v != ':') { if (*v == '\"' || *v == '\'' || *v == ' ' || *v == '\t') { v++; continue; } break; }
            if (*v != ':') return -1;
            v++; while (*v == ' ' || *v == '\t') v++;
            int sign = 1;
            if (*v == '-') { sign = -1; v++; } else if (*v == '+') v++;
            int n = 0, found = 0;
            while (*v >= '0' && *v <= '9') { n = n * 10 + (*v - '0'); v++; found = 1; }
            if (found) { *value = n * sign; return 0; }
            return -1;
        }
        p = key_pos;
        while (*p && *p != ',' && *p != '}' && *p != ']') p++;
        if (*p) p++;
    }
    return -1;
}

static int json_has_command(const char *json, const char *command)
{
    char pattern[40];
    int n = snprintf(pattern, sizeof(pattern), "\"cmd\":\"%s\"", command);
    return n > 0 && n < (int)sizeof(pattern) && strstr(json, pattern) != NULL;
}

static void handle_relay_command(const char *json)
{
    int relay_id, relay_state;
    if (json_get_int(json, "relay", &relay_id) != 0)
        return;
    if (json_get_int(json, "state", &relay_state) != 0)
        return;
    if (relay_state != 0 && relay_state != 1) return;
    if (relay_id < 1 || relay_id > RELAY_COUNT) return;

    Relay_SetState((uint8_t)relay_id, (uint8_t)relay_state);
    g_lcd_state.last_update_tick = HAL_GetTick();
    osSemaphoreRelease(LcdUpdateSemaphore);
}

/* -------- config.set 命令 ---------- */
static void handle_config_command(const char *json)
{
    int ip_parts[4];
    int port;
    /* 提取 IP 各部分: ip1~ip4 */
    if (json_get_int(json, "ip1", &ip_parts[0]) != 0) return;
    if (json_get_int(json, "ip2", &ip_parts[1]) != 0) return;
    if (json_get_int(json, "ip3", &ip_parts[2]) != 0) return;
    if (json_get_int(json, "ip4", &ip_parts[3]) != 0) return;
    if (json_get_int(json, "port", &port) != 0) return;
    if (port < 1 || port > 65535) return;

    uint32_t ip = ((uint32_t)ip_parts[3] << 24) |
                  ((uint32_t)ip_parts[2] << 16) |
                  ((uint32_t)ip_parts[1] <<  8) |
                  (uint32_t)ip_parts[0];

    RTC_SaveBrokerConfig(ip, (uint16_t)port);

    /* 复位 MCU 生效（记录原因，重启后屏上显示 CFG:SET） */
    LCD_Diag_ConfigReset();
    NVIC_SystemReset();
}

static void dispatch_command(const char *json)
{
    if (json_has_command(json, "relay.set")) {
        handle_relay_command(json);
    } else if (json_has_command(json, "config.set")) {
        handle_config_command(json);
    }
}

/* -------- MQTT 回调 ---------- */
static void mqtt_pub_cb(void *arg, err_t err) { (void)arg; (void)err; }

static void mqtt_data_cb(void *arg, const u8_t *data, u16_t len, u8_t flags)
{
    /* 本回调运行在 lwIP 的 tcpip 线程，栈很小（TCPIP_THREAD_STACKSIZE）。
       这里不能放大的局部变量，也不能做 UART 打印（DBG_PRINT 会额外吃 128 字节栈），
       只做拷贝入队；日志由 MQTT 任务打印。 */
    static CmdMsg_t msg;   /* tcpip 线程串行执行，可复用 */
    uint16_t n = len;

    (void)arg; (void)flags;
    if (data == NULL || len == 0 || g_cmd_queue == NULL) return;

    LCD_Diag_Stage(1);   /* 阶段码：收到 MQTT 下行数据（tcpip 线程） */
    if (n > CMD_MSG_MAX - 1) n = CMD_MSG_MAX - 1;
    msg.len = n;
    memcpy(msg.data, data, n);   /* data 指针只在回调期间有效，必须复制 */
    msg.data[n] = '\0';

    osMessageQueuePut(g_cmd_queue, &msg, 0, 0);
    LCD_Diag_Stage(2);
}

/* 收到发布报文时会先调用 topic 回调；这里不需要额外处理 */
static void mqtt_pub_cb_topic(void *arg, const char *topic, u32_t tot_len)
{
    (void)arg; (void)topic; (void)tot_len;
}

static void mqtt_sub_cb(void *arg, err_t err)
{
    (void)arg;
    DBG_PRINT("MQTT subscribe %s", (err == ERR_OK) ? "OK" : "FAIL");
}

/*
 * 连接状态回调
 * 运行在 tcpip 线程（此时 lwIP 核心锁已被 tcpip 线程持有），因此：
 *  - 这里只记录状态、刷新 LCD，不能调用 mqtt_* API；
 *  - 也不能释放 g_mqtt_client（lwIP 内部从回调返回后还会继续使用该对象）。
 * 客户端的断开/重连统一由 MQTT 任务处理。
 */
static void mqtt_connection_cb(mqtt_client_t *client, void *arg, mqtt_connection_status_t status)
{
    (void)client; (void)arg;
    if (status == MQTT_CONNECT_ACCEPTED) {
        g_subscribed = 0;
        g_lcd_state.tcp_connected = 1;
        {
            char ip_port[24];
            snprintf(ip_port, sizeof(ip_port), "%s:%u", g_broker_ip, g_broker_port);
            LCD_SetTcpStatus(1, ip_port);
        }
        osSemaphoreRelease(LcdUpdateSemaphore);
        g_mqtt_state = MQTT_STATE_CONNECTED;
        DBG_PRINT("MQTT connected");
    } else {
        g_lcd_state.tcp_connected = 0;
        osSemaphoreRelease(LcdUpdateSemaphore);
        g_mqtt_state = MQTT_STATE_RECONNECT;
        g_last_disc_reason = (int)status;   /* 记录断开原因码 */
        DBG_PRINT("MQTT disconnect/error: %d", status);
    }
}

/* -------- 发布状态 ---------- */
void MQTT_Publish_Status(void)
{
    if (g_mqtt_client == NULL) return;

    char payload[192];
    char temp_str[16], level_str[16], ph_str[16], orp_str[16];

    if (g_sensors[SENSOR_TEMP].valid)
        snprintf(temp_str, sizeof(temp_str), "%.1f", (double)g_sensors[SENSOR_TEMP].value);
    else
        snprintf(temp_str, sizeof(temp_str), "null");

    if (g_sensors[SENSOR_LEVEL].valid)
        snprintf(level_str, sizeof(level_str), "%.1f", (double)g_sensors[SENSOR_LEVEL].value);
    else
        snprintf(level_str, sizeof(level_str), "null");

    if (g_sensors[SENSOR_PH].valid)
        snprintf(ph_str, sizeof(ph_str), "%.2f", (double)g_sensors[SENSOR_PH].value);
    else
        snprintf(ph_str, sizeof(ph_str), "null");

    if (g_sensors[SENSOR_ORP].valid)
        snprintf(orp_str, sizeof(orp_str), "%.0f", (double)g_sensors[SENSOR_ORP].value);
    else
        snprintf(orp_str, sizeof(orp_str), "null");

    int n = snprintf(payload, sizeof(payload),
        "{\"relay\":[%d,%d,%d,%d,%d,%d,%d,%d],\"temp\":%s,\"level\":%s,\"ph\":%s,\"orp\":%s}",
        g_relays[0].state, g_relays[1].state,
        g_relays[2].state, g_relays[3].state,
        g_relays[4].state, g_relays[5].state,
        g_relays[6].state, g_relays[7].state,
        temp_str, level_str, ph_str, orp_str);

    /* mqtt_publish 会直接改客户端内部的发送环形缓冲，必须持核心锁，
       否则会和 tcpip 线程的发送流程并发、破坏报文（Broker 侧表现为突然断开） */
    LOCK_TCPIP_CORE();
    err_t err = ERR_CLSD;
    if (mqtt_client_is_connected(g_mqtt_client)) {
        err = mqtt_publish(g_mqtt_client, TOPIC_STATUS, payload, n, 0, 0, mqtt_pub_cb, NULL);
    }
    UNLOCK_TCPIP_CORE();

    if (err == ERR_OK) {
        g_pub_fail = 0;
        DBG_PRINT("Pub(%d)", n);
    } else {
        if (g_pub_fail < 100) g_pub_fail++;
        DBG_PRINT("Pub FAIL(%d) err=%d", n, (int)err);
    }
}

/* -------- 连接 Broker ---------- */
static err_t connect_to_broker(void)
{
    BrokerConfig_t cfg = RTC_LoadBrokerConfig();
    ip_addr_t ipaddr;
    ipaddr.addr = cfg.ip;
    err_t err;

    /* 客户端只创建一次，断线重连复用同一个实例。
       注意不能反复 mqtt_client_free()：回调/异步连接可能还在使用该对象，
       释放会造成 use-after-free（表现为偶发掉线、甚至死机重启）。 */
    if (g_mqtt_client == NULL) {
        LOCK_TCPIP_CORE();
        g_mqtt_client = mqtt_client_new();
        UNLOCK_TCPIP_CORE();
        if (g_mqtt_client == NULL) {
            DBG_PRINT("MQTT client_new FAILED");
            return ERR_MEM;
        }
    }

    char ip_str[16];
    IP_U32ToStr(cfg.ip, ip_str);
    strcpy(g_broker_ip, ip_str);
    g_broker_port = cfg.port;
    DBG_PRINT("MQTT connecting %s:%d...", ip_str, cfg.port);

    struct mqtt_connect_client_info_t ci;
    memset(&ci, 0, sizeof(ci));
    ci.client_id  = g_client_id;
    ci.keep_alive = MQTT_KEEPALIVE_S;

    /* mqtt_client_connect 会重建 PCB/发送缓冲，必须持核心锁 */
    LOCK_TCPIP_CORE();
    err = mqtt_client_connect(g_mqtt_client, &ipaddr, cfg.port,
                              mqtt_connection_cb, NULL, &ci);
    UNLOCK_TCPIP_CORE();
    return err;
}

/* -------- 主任务 ---------- */
void MQTT_Client_Task(void *argument)
{
    (void)argument;

    /* 等待 LwIP 初始化 */
    extern osSemaphoreId_t LwipReadySemaphore;
    osSemaphoreAcquire(LwipReadySemaphore, osWaitForever);

    /* 等待网口链路建立 */
    extern struct netif gnetif;
    while (!netif_is_link_up(&gnetif)) {
        osDelay(200);
    }
    osDelay(2000);  /* 链路刚稳定，再等2秒 */
    DBG_PRINT("Link UP, starting MQTT...");

    /* 唯一 ClientId（多台设备/测试客户端用同一 ID 会被 Broker 互相踢下线） */
    mqtt_build_client_id();
    DBG_PRINT("ClientId: %s", g_client_id);

    /* 先把 Broker 配置读进全局变量，LCD 在联网前也能显示目标服务器 */
    {
        BrokerConfig_t cfg = RTC_LoadBrokerConfig();
        IP_U32ToStr(cfg.ip, g_broker_ip);
        g_broker_port = cfg.port;
    }

    /* 创建命令队列 */
    g_cmd_queue = osMessageQueueNew(CMD_QUEUE_LEN, sizeof(CmdMsg_t), NULL);

    g_mqtt_state = MQTT_STATE_CONNECT;

    for (;;) {
        switch (g_mqtt_state) {
            case MQTT_STATE_CONNECT: {
                /* 链路不通则等待，避免无意义的连接尝试 */
                if (!netif_is_link_up(&gnetif)) {
                    osDelay(500);
                    break;
                }
                /* DHCP：等路由器分配 IP 后再连 Broker（0.0.0.0 = 尚未拿到地址） */
                if (ip4_addr_isany_val(*netif_ip4_addr(&gnetif))) {
                    /* 没有 DHCP 客户端（初始 dhcp_start 失败）时重试，5 秒一次 */
                    static uint32_t last_dhcp_try = 0;
                    if (netif_dhcp_data(&gnetif) == NULL &&
                        (last_dhcp_try == 0 || HAL_GetTick() - last_dhcp_try >= 5000)) {
                        last_dhcp_try = HAL_GetTick();
                        LOCK_TCPIP_CORE();
                        dhcp_start(&gnetif);
                        UNLOCK_TCPIP_CORE();
                        DBG_PRINT("retry dhcp_start");
                    }
                    osDelay(500);
                    break;
                }
                /* 拿到 DHCP 地址后打印一次，便于现场确认 */
                {
                    static uint8_t ip_logged = 0;
                    if (!ip_logged) {
                        char ip_buf[16];
                        ip4addr_ntoa_r(netif_ip4_addr(&gnetif), ip_buf, sizeof(ip_buf));
                        DBG_PRINT("DHCP IP: %s", ip_buf);
                        ip_logged = 1;
                    }
                }
                if (connect_to_broker() == ERR_OK) {
                    g_connect_start_tick = HAL_GetTick();
                    g_mqtt_state = MQTT_STATE_CONNECTING;  /* 异步连接中，等回调 */
                } else {
                    DBG_PRINT("mqtt_client_connect FAILED");
                    g_mqtt_state = MQTT_STATE_RECONNECT;
                }
                break;
            }

            case MQTT_STATE_CONNECTING: {
                /* 等待回调切换状态（CONNECTED 或 RECONNECT），并检测连接超时 */
                if ((HAL_GetTick() - g_connect_start_tick) >= CONNECT_TIMEOUT_MS) {
                    DBG_PRINT("MQTT connect timeout, retry...");
                    g_mqtt_state = MQTT_STATE_RECONNECT;
                }
                osDelay(100);
                break;
            }

            case MQTT_STATE_CONNECTED: {
                /* 监测 PHY 链路 — 拔网线时立即反应 */
                if (!netif_is_link_up(&gnetif)) {
                    DBG_PRINT("PHY link DOWN, disconnect MQTT");
                    g_last_disc_reason = MQTT_DISC_LINK_DOWN;
                    g_mqtt_state = MQTT_STATE_RECONNECT;
                    break;
                }
                /* 连接建立后订阅一次控制话题 */
                if (!g_subscribed && g_mqtt_client != NULL) {
                    err_t sub_err = ERR_CLSD;
                    LOCK_TCPIP_CORE();
                    if (mqtt_client_is_connected(g_mqtt_client)) {
                        mqtt_set_inpub_callback(g_mqtt_client, mqtt_pub_cb_topic, mqtt_data_cb, NULL);
                        sub_err = mqtt_subscribe(g_mqtt_client, TOPIC_CONTROL, 2, mqtt_sub_cb, NULL);
                    }
                    UNLOCK_TCPIP_CORE();
                    if (sub_err == ERR_OK) {
                        g_subscribed = 1;
                    }
                }
                /* 处理来自命令队列的消息（用 static 减少任务栈占用） */
                static CmdMsg_t cmd;
                while (osMessageQueueGet(g_cmd_queue, &cmd, NULL, 0) == osOK) {
                    LCD_Diag_Stage(11);   /* 阶段码：开始处理命令 */
                    DBG_PRINT("Process cmd: %s", cmd.data);
                    dispatch_command(cmd.data);
                    LCD_Diag_Stage(12);   /* 阶段码：命令处理完成 */
                }
                /* 固定间隔上报（1.5 秒），发送当前最新的采集值。
                   注意：不能按“采集批次事件”触发——采集周期 1s，
                   1.5s 不是它的整数倍，那样只能得到 1s/2s 间隔。 */
                {
                    uint32_t now = HAL_GetTick();
                    if (g_last_publish_tick == 0 ||
                        (now - g_last_publish_tick) >= PUBLISH_INTERVAL_MS) {
                        g_last_publish_tick = now;
                        LCD_Diag_Stage(13);   /* 阶段码：开始上报 */
                        MQTT_Publish_Status();
                        LCD_Diag_Stage(14);   /* 阶段码：上报完成 */
                        if (g_pub_fail >= PUB_FAIL_LIMIT) {
                            DBG_PRINT("publish keeps failing, reconnect");
                            g_last_disc_reason = MQTT_DISC_PUB_FAIL;
                            g_mqtt_state = MQTT_STATE_RECONNECT;
                            break;
                        }
                    }
                }
                osDelay(50);
                break;
            }

            case MQTT_STATE_RECONNECT:
                DBG_PRINT("MQTT reconnecting...");
                g_disc_count++;   /* 统计断连/重连次数（供屏上诊断） */
                /* 统一在这里断开：主动断开时 lwIP 不会再回调连接状态。
                   客户端不释放，下次 connect 时 lwIP 会 memset 复用。 */
                LOCK_TCPIP_CORE();
                if (g_mqtt_client != NULL) {
                    mqtt_disconnect(g_mqtt_client);
                }
                UNLOCK_TCPIP_CORE();
                g_subscribed = 0;
                g_pub_fail = 0;
                g_last_publish_tick = 0;   /* 重连成功后立刻上报一次 */
                g_lcd_state.tcp_connected = 0;
                osSemaphoreRelease(LcdUpdateSemaphore);
                osDelay(RECONNECT_DELAY_MS);
                g_mqtt_state = MQTT_STATE_CONNECT;
                break;

            default:
                osDelay(100);
                break;
        }
    }
}
