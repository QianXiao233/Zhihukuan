#include "rtc_config.h"
#include <string.h>
#include <stdio.h>

/* 后备寄存器直接地址 (STM32F407 RTC_BKP_DR) */
#define BKP_REG0  (RTC->BKP0R)
#define BKP_REG1  (RTC->BKP1R)
#define BKP_REG2  (RTC->BKP2R)
#define BKP_REG3  (RTC->BKP3R)
#define BKP_REG4  (RTC->BKP4R)
#define BKP_REG5  (RTC->BKP5R)

static uint32_t relay_state_check(uint32_t relay_mask)
{
    return relay_mask ^ 0xC35A96E1U;
}

/* 初始化 RTC 后备域（使能访问） */
void RTC_Config_Init(void)
{
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();
    /* RTC 时钟已在 SystemClock_Config 中使能，不需重复开启 */
}

/* 清除配置（恢复默认 Broker） */
void RTC_ClearConfig(void)
{
    BKP_REG0 = 0;  /* 清除 magic，下次启动使用默认值 */
}

/* 保存 */
void RTC_SaveBrokerConfig(uint32_t ip, uint16_t port)
{
    BKP_REG0 = BKP_MAGIC_VAL;
    BKP_REG1 = ip;
    BKP_REG2 = port;
}

/* 加载，校验失败返回默认值 */
BrokerConfig_t RTC_LoadBrokerConfig(void)
{
    BrokerConfig_t cfg;

    if (BKP_REG0 == BKP_MAGIC_VAL)
    {
        cfg.ip   = BKP_REG1;
        cfg.port = (uint16_t)(BKP_REG2 & 0xFFFF);
    }
    else
    {
        /* 无有效配置，使用编译期默认值 */
        cfg.ip   = IP_StrToU32(DEFAULT_BROKER_IP);
        cfg.port = DEFAULT_BROKER_PORT;
    }
    return cfg;
}

void RTC_SaveRelayState(uint32_t relay_mask)
{
    __HAL_RCC_PWR_CLK_ENABLE();
    HAL_PWR_EnableBkUpAccess();

    BKP_REG4 = relay_mask & 0xFFU;
    BKP_REG5 = relay_state_check(BKP_REG4);
    BKP_REG3 = BKP_RELAY_MAGIC_VAL;
}

uint32_t RTC_LoadRelayState(uint8_t *valid)
{
    uint32_t relay_mask = BKP_REG4 & 0xFFU;
    uint8_t ok = (BKP_REG3 == BKP_RELAY_MAGIC_VAL) &&
                 (BKP_REG5 == relay_state_check(relay_mask));

    if (valid != NULL)
        *valid = ok;
    return ok ? relay_mask : 0U;
}

/* IP 字符串 → uint32（LwIP 格式） */
uint32_t IP_StrToU32(const char *ip_str)
{
    unsigned int a, b, c, d;
    if (sscanf(ip_str, "%u.%u.%u.%u", &a, &b, &c, &d) == 4)
        return ((uint32_t)d << 24) | ((uint32_t)c << 16) |
               ((uint32_t)b <<  8) |  (uint32_t)a;
    return 0;
}

/* uint32 → IP 字符串 */
void IP_U32ToStr(uint32_t ip, char *out)
{
    snprintf(out, 16, "%lu.%lu.%lu.%lu",
             (unsigned long)(ip & 0xFF),
             (unsigned long)((ip >> 8) & 0xFF),
             (unsigned long)((ip >> 16) & 0xFF),
             (unsigned long)((ip >> 24) & 0xFF));
}
