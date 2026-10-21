#include "sensor_task.h"
#include "devices.h"
#include "lcd_state.h"
#include "delay.h"

osEventFlagsId_t SensorBatchEventFlags = NULL;

void Sensor_BatchEvent_Init(void)
{
    SensorBatchEventFlags = osEventFlagsNew(NULL);
}

/* 轮询间隔 */
#define POLL_INTERVAL_MS    1000

/*
 * 传感器轮询任务
 * 传感器硬件参数（Modbus 地址/寄存器/缩放方式）与状态统一由 devices.h 管理，
 * 此处只负责按节奏触发轮询并通知 LCD 刷新。
 */
void Sensor_Task(void *argument)
{
    (void)argument;

    osDelay(500);

    for (;;)
    {
        LCD_Diag_Stage(30);   /* 阶段码：传感器轮询 */
        Sensors_Poll();
        LCD_Diag_Stage(31);

        g_lcd_state.last_update_tick = HAL_GetTick();
        osSemaphoreRelease(LcdUpdateSemaphore);
        if (SensorBatchEventFlags != NULL)
            osEventFlagsSet(SensorBatchEventFlags, SENSOR_EVENT_BATCH_READY);

        osDelay(POLL_INTERVAL_MS);
    }
}
