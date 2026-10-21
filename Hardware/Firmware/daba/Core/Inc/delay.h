#ifndef __DELAY_H
#define __DELAY_H

#include "main.h"

void delay_init(void);      /* 初始化 DWT 延时 */
void delay_us(uint32_t us); /* 微秒延时 */
void delay_ms(uint32_t ms); /* 毫秒延时 */

#endif
