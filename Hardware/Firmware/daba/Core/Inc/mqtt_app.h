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
           1000=PHY 链路丢失, 1001=连续发布失败, 1002=连接超时 */
void MQTT_GetStats(int *last_reason, uint32_t *disc_count);

#endif
