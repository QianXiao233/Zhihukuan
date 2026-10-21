#ifndef __MODBUS_H
#define __MODBUS_H

#include "main.h"
#include "cmsis_os.h"
#include <stdint.h>

/* Modbus 功能码 */
#define MODBUS_FUNC_READ_HOLDING    0x03
#define MODBUS_FUNC_WRITE_SINGLE    0x06
#define MODBUS_FUNC_WRITE_MULTIPLE  0x10

/* 默认超时（ms） */
#define MODBUS_TIMEOUT_MS           500

/* RS485 中断接收缓冲（USART3 RXNE 中断逐字节填充） */
#define RS485_RX_BUF_MAX            64
extern volatile uint8_t  rs485_rx_buf[RS485_RX_BUF_MAX];
extern volatile uint16_t rs485_rx_cnt;

#define MODBUS_EVENT_FRAME_COMPLETE  0x0001U
#define MODBUS_EVENT_FRAME_ERROR     0x0002U
extern osEventFlagsId_t ModbusRxEventFlags;

/* RS485 方向控制引脚 */
#define RS485_DE_PORT               GPIOG
#define RS485_DE_PIN                GPIO_PIN_8
extern UART_HandleTypeDef huart3;
/* 初始化 RS485 (USART3, PB10-TX, PB11-RX, PG8-DIR, 9600) */
void MX_USART3_UART_Init(void);
void Modbus_RxEvent_Init(void);

/* 切换 RS485 方向 */
#define RS485_TX_EN()   HAL_GPIO_WritePin(RS485_DE_PORT, RS485_DE_PIN, GPIO_PIN_SET)
#define RS485_RX_EN()   HAL_GPIO_WritePin(RS485_DE_PORT, RS485_DE_PIN, GPIO_PIN_RESET)

/* CRC16 Modbus 计算 */
uint16_t Modbus_CRC16(uint8_t *buf, uint16_t len);

/* 读取保持寄存器 */
/* slave: 从机地址, reg: 寄存器地址, count: 数量, dest: 输出缓冲区 */
/* 返回 0=成功, -1=超时, -2=CRC错误, -3=异常响应 */
int Modbus_ReadHolding(uint8_t slave, uint16_t reg, uint16_t count, uint16_t *dest);

/* 发送裸数据帧（用于调试） */
void Modbus_SendRaw(uint8_t *data, uint16_t len);

#endif
