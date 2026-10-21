#ifndef __RTC_CONFIG_H
#define __RTC_CONFIG_H

#include "main.h"
#include <stdint.h>

/* 默认 Broker 配置（公网服务器） */
#define DEFAULT_BROKER_IP       "81.70.63.53"
#define DEFAULT_BROKER_PORT     1883

/* 后备寄存器索引 */
#define BKP_MAGIC_IDX   0   /* 校验标记 (0xA5A5A5A6=有效) */
#define BKP_IP_IDX      1   /* Broker IP (uint32_t, 大端) */
#define BKP_PORT_IDX    2   /* Broker Port (uint16_t, 低16位) */
/* 注意：magic 由 0xA5A5A5A5 变为 0xA5A5A5A6，
   使旧固件保存在 RTC 后备域的 Broker IP(192.168.10.247) 失效，
   升级后自动使用新的默认 Broker 地址。 */
#define BKP_MAGIC_VAL   0xA5A5A5A6
#define BKP_RELAY_MAGIC_VAL  0x524C5953U

/* Broker 配置结构体 */
typedef struct {
    uint32_t ip;        /* IP 地址 (4字节大端) */
    uint16_t port;      /* 端口 */
} BrokerConfig_t;

/* 初始化 RTC 后备域 */
void RTC_Config_Init(void);

/* 保存 Broker 配置到 RTC 后备寄存器 */
void RTC_SaveBrokerConfig(uint32_t ip, uint16_t port);

/* 清除 RTC 配置（恢复默认值） */
void RTC_ClearConfig(void);

/* 加载 Broker 配置，校验失败则返回默认值 */
BrokerConfig_t RTC_LoadBrokerConfig(void);
void RTC_SaveRelayState(uint32_t relay_mask);
uint32_t RTC_LoadRelayState(uint8_t *valid);

/* IP 地址字符串 ↔ uint32_t 互转 */
uint32_t IP_StrToU32(const char *ip_str);
void     IP_U32ToStr(uint32_t ip, char *out);

#endif
