#ifndef __MQTT_APP_H
#define __MQTT_APP_H

#include <stdint.h>

/* MQTT 客户端任务 */
void MQTT_Client_Task(void *argument);

/* 发布状态（可从传感器任务调用） */
void MQTT_Publish_Status(void);

/* 获取当前 Broker IP/端口（供 LCD 显示，避免 UI 任务里解析 RTC 配置） */
void MQTT_GetBrokerInfo(char *ip, int ip_len, uint16_t *port);

/* 诊断信息：最近一次断开原因码 + 断连次数
   原因码：0..255 = lwIP MQTT 状态码（256=对端断开, 257=超时/keepalive）
           1000=PHY 链路丢失, 1001=连续发布失败, 1002=连接超时,
           1003=网络卡死, 1004=TCP 已断但状态未更新 */
void MQTT_GetStats(int *last_reason, uint32_t *disc_count);

/* 连接统计：成功次数 / 尝试次数（屏上显示 C:ok/attempts） */
void MQTT_GetConnectStats(uint32_t *ok_count, uint32_t *attempts);

/* 最近一次连接结果：0=成功，<0=lwIP 错误码（-4=无路由），1002=TCP 握手 10s 超时 */
int MQTT_GetLastConnErr(void);

/* 网络看门狗（由心跳任务每 500ms 调用）：
   链路 UP 但 60s 无任何网络活动 → 整机自动复位。
   链路断开的兜底在 EthLink 线程里（断开 30s 自动复位）。
   只在本次开机成功连过 Broker 后才生效，避免无网环境反复重启。 */
void MQTT_NetWatchdogTick(void);

#endif
