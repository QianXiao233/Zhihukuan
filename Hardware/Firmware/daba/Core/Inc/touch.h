#ifndef __TOUCH_H
#define __TOUCH_H

#include "main.h"
#include <stdint.h>

/* =====================================================================
 * XPT2046 电阻触摸驱动（探索者 STM32F407 触摸屏排线）
 *
 * 引脚（与例程一致，原继电器已让出）：
 *   TCS  = PC13  片选
 *   TCLK = PB0   时钟
 *   TDIN = PF11  数据输入 (MOSI)
 *   DOUT = PB2   数据输出 (MISO)
 *   PEN  = PB1   按下检测（低电平=按下）
 * ===================================================================== */

#define TOUCH_CS_PIN    GPIO_PIN_13
#define TOUCH_CS_PORT   GPIOC
#define TOUCH_CLK_PIN   GPIO_PIN_0
#define TOUCH_CLK_PORT  GPIOB
#define TOUCH_DIN_PIN   GPIO_PIN_11
#define TOUCH_DIN_PORT  GPIOF
#define TOUCH_DOUT_PIN  GPIO_PIN_2
#define TOUCH_DOUT_PORT GPIOB
#define TOUCH_PEN_PIN   GPIO_PIN_1
#define TOUCH_PEN_PORT  GPIOB

/* XPT2046 读命令 */
#define TOUCH_CMD_RDX   0xD0    /* 读 X */
#define TOUCH_CMD_RDY   0x90    /* 读 Y */

/* ---- 坐标映射（硬编码近似，方向不对时改下面两个翻转宏） ----
 * XPT2046 输出 12bit (0~4095)，线性映射到屏幕分辨率。
 * 若触摸点与按钮错位，调整 xfac/yfac；方向反了改翻转宏。
 */
#define TOUCH_XFAC      0.078f      /* ≈ 320/4096 */
#define TOUCH_YFAC      0.117f      /* ≈ 480/4096 */
#define TOUCH_XOFF      0
#define TOUCH_YOFF      0
#define TOUCH_XFLIP     0           /* 1 = X 反向 */
#define TOUCH_YFLIP     0           /* 1 = Y 反向（实测 XPT2046 Y 轴方向与屏幕一致，无需翻转） */

/* 当前触摸状态（Touch_Scan 更新） */
extern volatile uint16_t touch_x;
extern volatile uint16_t touch_y;
extern volatile uint8_t  touch_pressed;   /* 1=当前按下 */

/* 初始化触摸屏 GPIO */
void Touch_Init(void);

/* 扫描一次触摸：返回 1=有按下（更新 touch_x/touch_y/touch_pressed），0=无 */
uint8_t Touch_Scan(void);

#endif /* __TOUCH_H */
