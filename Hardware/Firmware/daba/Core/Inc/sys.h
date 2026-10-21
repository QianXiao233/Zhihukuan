#ifndef __SYS_H
#define __SYS_H

#include "stdint.h"

/* 类型定义 */
typedef uint8_t     u8;
typedef uint16_t    u16;
typedef uint32_t    u32;
typedef volatile uint16_t vu16;
typedef volatile uint32_t vu32;

/* 位带操作 — PBout(n) 用于 LCD 背光 */
#define BITBAND(addr, bitnum)  ((addr & 0xF0000000) + 0x2000000 + ((addr & 0xFFFFF) << 5) + (bitnum << 2))
#define MEM_ADDR(addr)         *((volatile unsigned long *)(addr))

#define PBout(n)  MEM_ADDR(BITBAND(((uint32_t)&(GPIOB->ODR)), n))

#endif
