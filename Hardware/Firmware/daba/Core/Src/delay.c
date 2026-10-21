#include "delay.h"

static uint32_t g_us_tick = 0;

/**
  * @brief  初始化 DWT 延时
  *         使用 Cortex-M4 的 DWT 周期计数器实现微秒级延时
  */
void delay_init(void)
{
    /* 使能 DWT 外设 */
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;

    /* 复位 DWT 计数器 */
    DWT->CYCCNT = 0;

    /* 使能 DWT 周期计数器 */
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;

    /* 计算每微秒的时钟周期数 (168MHz = 168 ticks/us) */
    g_us_tick = HAL_RCC_GetHCLKFreq() / 1000000;
}

/**
  * @brief  微秒延时
  * @param  us  延时微秒数
  */
void delay_us(uint32_t us)
{
    uint32_t start = DWT->CYCCNT;
    uint32_t ticks = us * g_us_tick;
    while ((DWT->CYCCNT - start) < ticks);
}

/**
  * @brief  毫秒延时
  * @param  ms  延时毫秒数
  */
void delay_ms(uint32_t ms)
{
    HAL_Delay(ms);
}
