#include "touch.h"
#include "delay.h"

volatile uint16_t touch_x = 0;
volatile uint16_t touch_y = 0;
volatile uint8_t  touch_pressed = 0;

/* ---------- GPIO 引脚操作 ---------- */
#define T_CS_LOW()   HAL_GPIO_WritePin(TOUCH_CS_PORT, TOUCH_CS_PIN, GPIO_PIN_RESET)
#define T_CS_HIGH()  HAL_GPIO_WritePin(TOUCH_CS_PORT, TOUCH_CS_PIN, GPIO_PIN_SET)
#define T_CLK_LOW()  HAL_GPIO_WritePin(TOUCH_CLK_PORT, TOUCH_CLK_PIN, GPIO_PIN_RESET)
#define T_CLK_HIGH() HAL_GPIO_WritePin(TOUCH_CLK_PORT, TOUCH_CLK_PIN, GPIO_PIN_SET)
#define T_DIN_HIGH() HAL_GPIO_WritePin(TOUCH_DIN_PORT, TOUCH_DIN_PIN, GPIO_PIN_SET)
#define T_DIN_LOW()  HAL_GPIO_WritePin(TOUCH_DIN_PORT, TOUCH_DIN_PIN, GPIO_PIN_RESET)
#define T_DOUT_GET() HAL_GPIO_ReadPin(TOUCH_DOUT_PORT, TOUCH_DOUT_PIN)
#define T_PEN_GET()  HAL_GPIO_ReadPin(TOUCH_PEN_PORT, TOUCH_PEN_PIN)

void Touch_Init(void)
{
    GPIO_InitTypeDef g = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOF_CLK_ENABLE();

    /* PEN (PB1)：上拉输入 */
    g.Pin = TOUCH_PEN_PIN;
    g.Mode = GPIO_MODE_INPUT;
    g.Pull = GPIO_PULLUP;
    g.Speed = GPIO_SPEED_HIGH;
    HAL_GPIO_Init(TOUCH_PEN_PORT, &g);

    /* DOUT (PB2)：浮空输入 */
    g.Pin = TOUCH_DOUT_PIN;
    g.Mode = GPIO_MODE_INPUT;
    g.Pull = GPIO_NOPULL;
    HAL_GPIO_Init(TOUCH_DOUT_PORT, &g);

    /* TDIN/TCLK/TCS：推挽输出 */
    g.Mode = GPIO_MODE_OUTPUT_PP;
    g.Pull = GPIO_NOPULL;
    g.Speed = GPIO_SPEED_HIGH;

    g.Pin = TOUCH_DIN_PIN;
    HAL_GPIO_Init(TOUCH_DIN_PORT, &g);
    g.Pin = TOUCH_CLK_PIN;
    HAL_GPIO_Init(TOUCH_CLK_PORT, &g);
    g.Pin = TOUCH_CS_PIN;
    HAL_GPIO_Init(TOUCH_CS_PORT, &g);

    /* 默认电平 */
    T_CS_HIGH();
    T_CLK_LOW();
    T_DIN_LOW();
}

/* 写一个字节（上升沿有效） */
static void tp_write_byte(uint8_t num)
{
    for (uint8_t i = 0; i < 8; i++) {
        if (num & 0x80) T_DIN_HIGH();
        else            T_DIN_LOW();
        num <<= 1;
        T_CLK_LOW();
        delay_us(1);
        T_CLK_HIGH();
    }
}

/* 读一次 AD 转换值（16 位，高 12 位有效） */
static uint16_t tp_read_ad(uint8_t cmd)
{
    uint16_t num = 0;

    T_CLK_LOW();
    T_DIN_LOW();
    T_CS_LOW();
    tp_write_byte(cmd);
    delay_us(6);            /* 转换时间 */
    T_CLK_LOW();
    delay_us(1);
    T_CLK_HIGH();           /* 清 BUSY */
    delay_us(1);
    T_CLK_LOW();

    for (uint8_t i = 0; i < 16; i++) {
        T_CLK_LOW();
        delay_us(1);
        num <<= 1;
        if (T_DOUT_GET() == GPIO_PIN_SET) num++;
        T_CLK_HIGH();
    }
    T_CS_HIGH();
    return (num >> 4);      /* 高 12 位 */
}

/* 带滤波读坐标：采样 5 次，去掉最大最小值取平均 */
#define READ_TIMES  5
static uint16_t tp_read_xoy(uint8_t cmd)
{
    uint16_t buf[READ_TIMES];
    uint16_t sum = 0;

    for (uint8_t i = 0; i < READ_TIMES; i++)
        buf[i] = tp_read_ad(cmd);

    /* 冒泡排序 */
    for (uint8_t i = 0; i < READ_TIMES - 1; i++) {
        for (uint8_t j = i + 1; j < READ_TIMES; j++) {
            if (buf[i] > buf[j]) {
                uint16_t t = buf[i];
                buf[i] = buf[j];
                buf[j] = t;
            }
        }
    }

    for (uint8_t i = 1; i < READ_TIMES - 1; i++)
        sum += buf[i];
    return sum / (READ_TIMES - 2);
}

uint8_t Touch_Scan(void)
{
    /* PEN 低电平 = 有触摸 */
    if (T_PEN_GET() == GPIO_PIN_RESET) {
        uint16_t rx = tp_read_xoy(TOUCH_CMD_RDX);
        uint16_t ry = tp_read_xoy(TOUCH_CMD_RDY);

        uint32_t x = (uint32_t)(rx * TOUCH_XFAC) + TOUCH_XOFF;
        uint32_t y = (uint32_t)(ry * TOUCH_YFAC) + TOUCH_YOFF;

#if TOUCH_XFLIP
        x = 319 - x;
#endif
#if TOUCH_YFLIP
        y = 479 - y;
#endif

        touch_x = (x < 320) ? (uint16_t)x : 319;
        touch_y = (y < 480) ? (uint16_t)y : 479;
        touch_pressed = 1;
        return 1;
    }

    touch_pressed = 0;
    return 0;
}
