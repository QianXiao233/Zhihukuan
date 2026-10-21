#include "lcd_state.h"
#include <string.h>

volatile LCD_State_t g_lcd_state;
osSemaphoreId_t LcdUpdateSemaphore;

void LCD_State_Init(void)
{
    memset((void*)&g_lcd_state, 0, sizeof(g_lcd_state));
    g_lcd_state.tcp_connected = 0;
    strcpy((char*)g_lcd_state.client_ip, "0.0.0.0");
    g_lcd_state.last_update_tick = 0;

    LcdUpdateSemaphore = osSemaphoreNew(1, 0, NULL);
}

void LCD_SetTcpStatus(uint8_t connected, const char *ip)
{
    g_lcd_state.tcp_connected = connected ? 1 : 0;
    if (ip) {
        strncpy((char*)g_lcd_state.client_ip, ip, sizeof(g_lcd_state.client_ip) - 1);
        g_lcd_state.client_ip[sizeof(g_lcd_state.client_ip) - 1] = '\0';
    }
    g_lcd_state.last_update_tick = HAL_GetTick();
}

/* ================= 崩溃/复位诊断（复位不清零区） ================= */

/* 放在 .noinit 段：IWDG/软件复位不会清零，只有上电才丢失；用 magic 校验 */
__attribute__((section(".noinit"))) volatile LCD_DiagRaw_t g_diag;

static LCD_DiagView_t s_diag_view;

static void diag_copy_name(char *dst, const volatile char *src, int max)
{
    int i = 0;

    if (src != NULL) {
        while ((i < max - 1) && (src[i] != '\0')) {
            dst[i] = src[i];
            i++;
        }
    }
    dst[i] = '\0';
}

void LCD_Diag_Init(void)
{
    if (g_diag.magic != LCD_DIAG_MAGIC) {
        /* 上电（RAM 随机值）：初始化 */
        g_diag.magic = LCD_DIAG_MAGIC;
        g_diag.stage = 0;
        g_diag.ovf_count = 0;
        g_diag.ovf_task[0] = '\0';
        g_diag.cfg_reset = 0;
        memset(&s_diag_view, 0, sizeof(s_diag_view));
        return;
    }

    /* 保留上次运行的信息供 LCD 显示，然后清空 raw 供本次重新记录 */
    s_diag_view.ovf_count = g_diag.ovf_count;
    diag_copy_name(s_diag_view.ovf_task, g_diag.ovf_task, sizeof(s_diag_view.ovf_task));
    s_diag_view.cfg_reset = g_diag.cfg_reset;
    s_diag_view.crash_stage = g_diag.stage;

    g_diag.ovf_count = 0;
    g_diag.ovf_task[0] = '\0';
    g_diag.cfg_reset = 0;
    g_diag.stage = 0;
}

const LCD_DiagView_t *LCD_Diag_View(void)
{
    return &s_diag_view;
}

void LCD_Diag_Stage(uint32_t stage)
{
    if (g_diag.magic == LCD_DIAG_MAGIC) {
        g_diag.stage = stage;
    }
}

void LCD_Diag_Overflow(const char *task_name)
{
    if (g_diag.magic != LCD_DIAG_MAGIC) {
        g_diag.magic = LCD_DIAG_MAGIC;
    }
    g_diag.ovf_count++;
    diag_copy_name((char *)g_diag.ovf_task, task_name, sizeof(g_diag.ovf_task));
}

void LCD_Diag_ConfigReset(void)
{
    if (g_diag.magic != LCD_DIAG_MAGIC) {
        g_diag.magic = LCD_DIAG_MAGIC;
    }
    g_diag.cfg_reset = 1;
}
