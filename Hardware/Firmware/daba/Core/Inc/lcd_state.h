#ifndef __LCD_STATE_H
#define __LCD_STATE_H

#include "main.h"
#include "cmsis_os.h"

/* 网络/系统共享状态（继电器、传感器等设备数据见 devices.h） */
typedef struct {
    uint8_t  tcp_connected;               /* 0=未连接, 1=已连接 */
    char     client_ip[24];               /* Broker IP:端口 */
    uint32_t last_update_tick;            /* 最后更新时间戳 */
} LCD_State_t;

/* 全局状态实例 */
extern volatile LCD_State_t g_lcd_state;

/* LCD 更新信号量 — TCP 任务释放，LCD 任务等待 */
extern osSemaphoreId_t LcdUpdateSemaphore;

/* 初始化共享状态 */
void LCD_State_Init(void);

/* 快捷设置 TCP 状态 */
void LCD_SetTcpStatus(uint8_t connected, const char *ip);

/* ================= 崩溃/复位诊断（保存在复位不清零的 .noinit 区） ================= */
#define LCD_DIAG_MAGIC   0x44494147u   /* "DIAG" */

typedef struct {
    uint32_t magic;
    uint32_t stage;        /* 当前执行阶段码（运行中持续更新） */
    uint32_t ovf_count;    /* 栈溢出次数 */
    char     ovf_task[16]; /* 发生栈溢出的任务名 */
    uint8_t  cfg_reset;    /* 1 = 由 config.set 主动复位 */
} LCD_DiagRaw_t;

typedef struct {
    uint32_t ovf_count;    /* 上次运行：栈溢出次数 */
    char     ovf_task[16]; /* 上次运行：溢出任务名 */
    uint8_t  cfg_reset;    /* 上次运行：是否 config.set 复位 */
    uint32_t crash_stage;  /* 上次运行最后阶段码 */
} LCD_DiagView_t;

extern volatile LCD_DiagRaw_t g_diag;

/* 开机调用：把上次运行的诊断信息搬到 view 中，并清空 raw 供本次记录 */
void LCD_Diag_Init(void);
const LCD_DiagView_t *LCD_Diag_View(void);

/* 记录当前执行阶段（只写 RAM，开销极小） */
void LCD_Diag_Stage(uint32_t stage);

/* 栈溢出钩子调用：记录任务名 */
void LCD_Diag_Overflow(const char *task_name);

/* config.set 主动复位前调用 */
void LCD_Diag_ConfigReset(void);

#endif
