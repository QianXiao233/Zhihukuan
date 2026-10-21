#include "modbus.h"
#include "delay.h"
#include "cmsis_os.h"
#include <string.h>

UART_HandleTypeDef huart3;

/* RS485 中断接收缓冲 */
volatile uint8_t  rs485_rx_buf[RS485_RX_BUF_MAX];
volatile uint16_t rs485_rx_cnt = 0;
osEventFlagsId_t ModbusRxEventFlags = NULL;

typedef enum {
    MODBUS_RX_IDLE = 0,
    MODBUS_RX_WAITING,
    MODBUS_RX_RECEIVING,
    MODBUS_RX_COMPLETE,
    MODBUS_RX_ERROR
} ModbusRxState_t;

static volatile ModbusRxState_t modbus_rx_state = MODBUS_RX_IDLE;
static volatile uint16_t modbus_rx_expected_len = 0;
static volatile uint16_t modbus_rx_frame_len = 0;

void Modbus_RxEvent_Init(void)
{
    ModbusRxEventFlags = osEventFlagsNew(NULL);
}

/* printf 重定向到 USART3 */
int __io_putchar(int ch) { extern UART_HandleTypeDef huart1; HAL_UART_Transmit(&huart1, (uint8_t*)&ch, 1, 100); return ch; }

/* USART3 初始化（PB10-TX, PB11-RX, PG8-DIR, 9600-8N1, 纯轮询） */
void MX_USART3_UART_Init(void)
{
    GPIO_InitTypeDef gpio = {0};

    __HAL_RCC_USART3_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOG_CLK_ENABLE();

    // ===== USART3_TX (PB10) =====
    gpio.Pin = GPIO_PIN_10;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_PULLUP;
    gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    gpio.Alternate = GPIO_AF7_USART3;
    HAL_GPIO_Init(GPIOB, &gpio);

    // ===== USART3_RX (PB11) =====
    gpio.Pin = GPIO_PIN_11;
    gpio.Mode = GPIO_MODE_AF_PP;
    gpio.Pull = GPIO_NOPULL;  // RX 使用外部 RS485 总线驱动
    gpio.Alternate = GPIO_AF7_USART3;
    HAL_GPIO_Init(GPIOB, &gpio);

    // ===== RS485 方向控制 (PG8) =====
    gpio.Pin = GPIO_PIN_8;
    gpio.Mode = GPIO_MODE_OUTPUT_PP;
    gpio.Pull = GPIO_NOPULL;  // 输出模式下无影响
    gpio.Speed = GPIO_SPEED_FREQ_HIGH;
    HAL_GPIO_Init(GPIOG, &gpio);

    // 默认设置为接收模式
    RS485_RX_EN();
    HAL_Delay(1);  // 确保电平稳定

    // ===== USART3 配置 =====
    huart3.Instance = USART3;
    huart3.Init.BaudRate = 9600;
    huart3.Init.WordLength = UART_WORDLENGTH_8B;
    huart3.Init.StopBits = UART_STOPBITS_1;
    huart3.Init.Parity = UART_PARITY_NONE;
    huart3.Init.Mode = UART_MODE_TX_RX;
    huart3.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    huart3.Init.OverSampling = UART_OVERSAMPLING_16;

    if (HAL_UART_Init(&huart3) != HAL_OK) {
        // 初始化失败处理
        Error_Handler();
    }

    /* 使能 USART3 接收中断（RS485 中断接收，最稳定的收包方式） */
    HAL_NVIC_SetPriority(USART3_IRQn, 5, 0);
    HAL_NVIC_EnableIRQ(USART3_IRQn);
    __HAL_UART_ENABLE_IT(&huart3, UART_IT_RXNE);
}

/* USART3 接收中断：逐字节存入缓冲，ORE 溢出自愈 */
void USART3_IRQHandler(void)
{
    if (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_ORE)) {
        (void)huart3.Instance->SR;
        (void)huart3.Instance->DR;
        modbus_rx_state = MODBUS_RX_ERROR;
        __HAL_UART_DISABLE_IT(&huart3, UART_IT_RXNE);
        if (ModbusRxEventFlags != NULL)
            osEventFlagsSet(ModbusRxEventFlags, MODBUS_EVENT_FRAME_ERROR);
    }
    if (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_RXNE)) {
        uint8_t d = (uint8_t)(huart3.Instance->DR & 0xFF);
        if (modbus_rx_state == MODBUS_RX_WAITING)
            modbus_rx_state = MODBUS_RX_RECEIVING;

        if (modbus_rx_state == MODBUS_RX_RECEIVING &&
            rs485_rx_cnt < RS485_RX_BUF_MAX) {
            rs485_rx_buf[rs485_rx_cnt++] = d;

            if (rs485_rx_cnt == 3) {
                if (rs485_rx_buf[1] & 0x80U)
                    modbus_rx_expected_len = 5;
                else
                    modbus_rx_expected_len = 5U + rs485_rx_buf[2];

                if (modbus_rx_expected_len > RS485_RX_BUF_MAX) {
                    modbus_rx_state = MODBUS_RX_ERROR;
                    __HAL_UART_DISABLE_IT(&huart3, UART_IT_RXNE);
                    if (ModbusRxEventFlags != NULL)
                        osEventFlagsSet(ModbusRxEventFlags,
                                        MODBUS_EVENT_FRAME_ERROR);
                }
            }

            if (modbus_rx_expected_len != 0 &&
                rs485_rx_cnt >= modbus_rx_expected_len) {
                modbus_rx_frame_len = rs485_rx_cnt;
                modbus_rx_state = MODBUS_RX_COMPLETE;
                __HAL_UART_DISABLE_IT(&huart3, UART_IT_RXNE);
                if (ModbusRxEventFlags != NULL)
                    osEventFlagsSet(ModbusRxEventFlags,
                                    MODBUS_EVENT_FRAME_COMPLETE);
            }
        }
    }
}

/* CRC16 Modbus */
static const uint16_t crc16_table[] = {
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
    0xC601, 0x06C0, 0x0780, 0xC741, 0x0500, 0xC5C1, 0xC481, 0x0440,
    0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40,
    0x0A00, 0xCAC1, 0xCB81, 0x0B40, 0xC901, 0x09C0, 0x0880, 0xC841,
    0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40,
    0x1E00, 0xDEC1, 0xDF81, 0x1F40, 0xDD01, 0x1DC0, 0x1C80, 0xDC41,
    0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641,
    0xD201, 0x12C0, 0x1380, 0xD341, 0x1100, 0xD1C1, 0xD081, 0x1040,
    0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240,
    0x3600, 0xF6C1, 0xF781, 0x3740, 0xF501, 0x35C0, 0x3480, 0xF441,
    0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41,
    0xFA01, 0x3AC0, 0x3B80, 0xFB41, 0x3900, 0xF9C1, 0xF881, 0x3840,
    0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41,
    0xEE01, 0x2EC0, 0x2F80, 0xEF41, 0x2D00, 0xEDC1, 0xEC81, 0x2C40,
    0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640,
    0x2200, 0xE2C1, 0xE381, 0x2340, 0xE101, 0x21C0, 0x2080, 0xE041,
    0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240,
    0x6600, 0xA6C1, 0xA781, 0x6740, 0xA501, 0x65C0, 0x6480, 0xA441,
    0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41,
    0xAA01, 0x6AC0, 0x6B80, 0xAB41, 0x6900, 0xA9C1, 0xA881, 0x6840,
    0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41,
    0xBE01, 0x7EC0, 0x7F80, 0xBF41, 0x7D00, 0xBDC1, 0xBC81, 0x7C40,
    0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640,
    0x7200, 0xB2C1, 0xB381, 0x7340, 0xB101, 0x71C0, 0x7080, 0xB041,
    0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241,
    0x9601, 0x56C0, 0x5780, 0x9741, 0x5500, 0x95C1, 0x9481, 0x5440,
    0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40,
    0x5A00, 0x9AC1, 0x9B81, 0x5B40, 0x9901, 0x59C0, 0x5880, 0x9841,
    0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40,
    0x4E00, 0x8EC1, 0x8F81, 0x4F40, 0x8D01, 0x4DC0, 0x4C80, 0x8C41,
    0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641,
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040,
};

uint16_t Modbus_CRC16(uint8_t *buf, uint16_t len)
{
    uint16_t crc = 0xFFFF;
    for (uint16_t i = 0; i < len; i++)
        crc = (crc >> 8) ^ crc16_table[(crc ^ buf[i]) & 0xFF];
    return crc;
}

void Modbus_SendRaw(uint8_t *data, uint16_t len)
{
    /* 发送期间关闭接收中断，防止半双工自收回波进入缓冲 */
    __HAL_UART_DISABLE_IT(&huart3, UART_IT_RXNE);
    if (ModbusRxEventFlags != NULL)
        osEventFlagsClear(ModbusRxEventFlags,
                          MODBUS_EVENT_FRAME_COMPLETE |
                          MODBUS_EVENT_FRAME_ERROR);
    rs485_rx_cnt = 0;
    modbus_rx_expected_len = 0;
    modbus_rx_frame_len = 0;
    modbus_rx_state = MODBUS_RX_IDLE;

    /* 清接收残留与溢出 */
    while (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_RXNE) != RESET) {
        (void)(huart3.Instance->DR & 0xFF);
    }
    if (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_ORE)) {
        (void)huart3.Instance->DR;
    }

    RS485_TX_EN();
    HAL_Delay(1);  /* Wait for DE/RE to settle. */

    if (HAL_UART_Transmit(&huart3, data, len, 1000) == HAL_OK) {
        /* Half-duplex RS485: wait until the last bit is fully sent before switching to RX.
           加超时保护，防止 RS485 总线异常时无限等待 */
        uint32_t start = HAL_GetTick();
        while (__HAL_UART_GET_FLAG(&huart3, UART_FLAG_TC) == RESET) {
            if (HAL_GetTick() - start > 100) break;  /* 最多等 100ms */
        }
    }

    /* 发送结束后立刻切回接收，避免错过响应很快的从机首字节 */
    RS485_RX_EN();
    modbus_rx_state = MODBUS_RX_WAITING;
    __HAL_UART_ENABLE_IT(&huart3, UART_IT_RXNE);
}

int Modbus_ReadHolding(uint8_t slave, uint16_t reg, uint16_t count, uint16_t *dest)
{
    uint8_t tx_buf[8];
    uint8_t rx_buf[64];
    uint16_t crc;
    int expect_len = 2 + 1 + count * 2 + 2;

    if (count > 16) return -4;

    tx_buf[0] = slave;
    tx_buf[1] = MODBUS_FUNC_READ_HOLDING;
    tx_buf[2] = (reg >> 8) & 0xFF;
    tx_buf[3] = reg & 0xFF;
    tx_buf[4] = (count >> 8) & 0xFF;
    tx_buf[5] = count & 0xFF;
    crc = Modbus_CRC16(tx_buf, 6);
    tx_buf[6] = crc & 0xFF;
    tx_buf[7] = (crc >> 8) & 0xFF;

    Modbus_SendRaw(tx_buf, 8);

    /* 等中断接收缓冲收满 expect_len 字节（ISR 逐字节填充，不丢包） */
    uint32_t event = osEventFlagsWait(
        ModbusRxEventFlags,
        MODBUS_EVENT_FRAME_COMPLETE | MODBUS_EVENT_FRAME_ERROR,
        osFlagsWaitAny,
        800);
    if ((event & osFlagsError) != 0)
        return -1;
    if ((event & MODBUS_EVENT_FRAME_ERROR) != 0)
        return -3;
    if ((event & MODBUS_EVENT_FRAME_COMPLETE) == 0)
        return -1;

    __disable_irq();
    uint16_t frame_len = modbus_rx_frame_len;
    if (frame_len > sizeof(rx_buf))
        frame_len = sizeof(rx_buf);
    for (uint16_t i = 0; i < frame_len; i++)
        rx_buf[i] = rs485_rx_buf[i];
    modbus_rx_state = MODBUS_RX_IDLE;
    __enable_irq();

    if (frame_len < 5 || frame_len < expect_len) return -1;
    if (rx_buf[0] != slave) return -2;
    if (rx_buf[1] & 0x80) return -3;

    uint16_t recv_crc = rx_buf[frame_len - 2] |
                        ((uint16_t)rx_buf[frame_len - 1] << 8);
    if (recv_crc != Modbus_CRC16(rx_buf, frame_len - 2)) return -2;

    for (int i = 0; i < count; i++)
        dest[i] = (rx_buf[3 + i * 2] << 8) | rx_buf[4 + i * 2];
    return 0;
}
