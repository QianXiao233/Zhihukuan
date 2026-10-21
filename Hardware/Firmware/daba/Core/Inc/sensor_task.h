#ifndef __SENSOR_TASK_H
#define __SENSOR_TASK_H

#include "cmsis_os.h"

#define SENSOR_EVENT_BATCH_READY  0x0001U
extern osEventFlagsId_t SensorBatchEventFlags;

void Sensor_BatchEvent_Init(void);
void Sensor_Task(void *argument);

#endif
