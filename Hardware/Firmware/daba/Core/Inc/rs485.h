#ifndef __RS485_H
#define __RS485_H

#include "main.h"

/* RS485 方向控制 */
#define RS485_TX_EN()  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_7, GPIO_PIN_SET)
#define RS485_RX_EN()  HAL_GPIO_WritePin(GPIOD, GPIO_PIN_7, GPIO_PIN_RESET)

/* 外部中断服务函数 */
void USART3_IRQHandler(void);

/* 485 初始化 (USART3, PB10-TX, PB11-RX, PD7-DIR, 9600) */
void RS485_Init(void);

/* 发送 len 字节 */
void RS485_Send_Data(uint8_t *buf, uint8_t len);

/* 查询接收数据（等 10ms 无数据视为接收完毕） */
void RS485_Receive_Data(uint8_t *buf, uint8_t *len);

/* Modbus 读保持寄存器（基于 RS485_ 函数） */
int RS485_Modbus_ReadHolding(uint8_t slave, uint16_t reg, uint16_t count, uint16_t *dest);

#endif
