/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * File Name          : freertos.c
  * Description        : Code for freertos applications
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2026 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */

/* Includes ------------------------------------------------------------------*/
#include "FreeRTOS.h"
#include "task.h"
#include "main.h"
#include "cmsis_os.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <stdio.h>
#include <string.h>
#include "lcd.h"
#include "lcd_state.h"
#include "chinese_font.h"
#include "sensor_task.h"
#include "modbus.h"
#include "mqtt_app.h"
#include "devices.h"
#include "touch.h"
#include "lwip/netif.h"
#include "lwip/ip_addr.h"
/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */

/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN Variables */
osSemaphoreId_t LwipReadySemaphore;
/* USER CODE END Variables */
osThreadId_t HeartbeatTaskHandle;
const osThreadAttr_t HeartBeat_attributes = {
  .name = "HeartBeatTask",
  .stack_size = 512,
  .priority = (osPriority_t) osPriorityLow,
};
osThreadId_t StartupTaskHandle;
const osThreadAttr_t Startup_attributes = {
  .name = "StartupTask",
  .stack_size = 2048,   /* LCD_Init/LwIP 初始化 + printf，留足余量 */
  .priority = (osPriority_t) osPriorityBelowNormal,
};
osThreadId_t MqttClientTaskHandle;
const osThreadAttr_t MqttClient_attributes = {
  .name = "MqttClient",
  .stack_size = 3072,   /* 发布路径含 snprintf 浮点格式化，留足余量 */
  .priority = (osPriority_t) osPriorityNormal,
};
osThreadId_t LcdUpdateTaskHandle;
const osThreadAttr_t LcdUpdate_attributes = {
  .name = "LcdUpdate",
  .stack_size = 3072,   /* 大量 LCD 绘制 + snprintf（含浮点） */
  .priority = (osPriority_t) osPriorityBelowNormal,
};
osThreadId_t SensorTaskHandle;
const osThreadAttr_t Sensor_attributes = {
  .name = "Sensor",
  .stack_size = 1024,   /* Modbus 收发 + 重试 */
  .priority = (osPriority_t) osPriorityNormal,
};
osThreadId_t TouchTaskHandle;
const osThreadAttr_t Touch_attributes = {
  .name = "Touch",
  .stack_size = 1024,
  .priority = (osPriority_t) osPriorityNormal,
};

/* Heartbeat_Task includes */
#include "stm32f4xx_hal_iwdg.h"

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN FunctionPrototypes */

/* USER CODE END FunctionPrototypes */

void StartDefaultTask(void *argument);
void Heartbeat_Task(void *argument);
void Startup_Task(void *argument);
void MQTT_Client_Task(void *argument);
void LCD_Update_Task(void *argument);
void Sensor_Task(void *argument);
void Touch_Task(void *argument);
extern void MX_LWIP_Init(void);
void MX_FREERTOS_Init(void); /* (MISRA C 2004 rule 8.1) */

/**
  * @brief  FreeRTOS initialization
  * @param  None
  * @retval None
  */
void MX_FREERTOS_Init(void) {
  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* USER CODE BEGIN RTOS_MUTEX */
  /* add mutexes, ... */
  /* USER CODE END RTOS_MUTEX */

  /* USER CODE BEGIN RTOS_SEMAPHORES */
  /* 信号量：LwIP 初始化完成标志 */
  LwipReadySemaphore = osSemaphoreNew(1, 0, NULL);
  Modbus_RxEvent_Init();
  Sensor_BatchEvent_Init();
  /* 初始化共享状态 + LCD 更新信号量 */
  LCD_State_Init();
  /* USER CODE END RTOS_SEMAPHORES */

  /* USER CODE BEGIN RTOS_TIMERS */
  /* start timers, add new ones, ... */
  /* USER CODE END RTOS_TIMERS */

  /* USER CODE BEGIN RTOS_QUEUES */
  /* add queues, ... */
  /* USER CODE END RTOS_QUEUES */

  /* Create the thread(s) */
  HeartbeatTaskHandle = osThreadNew(Heartbeat_Task, NULL, &HeartBeat_attributes);

  /* USER CODE BEGIN RTOS_THREADS */
  /* 启动任务：调度器启动后初始化 LwIP */
  StartupTaskHandle = osThreadNew(Startup_Task, NULL, &Startup_attributes);
  /*LCD屏幕更新任务*/
  LcdUpdateTaskHandle = osThreadNew(LCD_Update_Task, NULL, &LcdUpdate_attributes);
  /* MQTT 客户端任务 */
  MqttClientTaskHandle = osThreadNew(MQTT_Client_Task, NULL, &MqttClient_attributes);
  /* 传感器轮询任务 */
  SensorTaskHandle = osThreadNew(Sensor_Task, NULL, &Sensor_attributes);
  /* 触摸扫描任务（屏幕按钮控制闸门） */
  TouchTaskHandle = osThreadNew(Touch_Task, NULL, &Touch_attributes);
  /* USER CODE END RTOS_THREADS */

  /* USER CODE BEGIN RTOS_EVENTS */
  /* add events, ... */
  /* USER CODE END RTOS_EVENTS */

}

/* 心跳任务 - 优先级最低 */
void Heartbeat_Task(void *argument)
{
  for(;;)
  {
    HAL_GPIO_TogglePin(LED_RED_Port, LED_RED_Pin);  // 翻转 LED

    /* 喂狗 — 如果系统卡死，IWDG 3秒后自动复位 */
    IWDG->KR = 0xAAAA;

    osDelay(500);                 // 500ms 闪一次
  }
}

/* Private application code --------------------------------------------------*/
/* USER CODE BEGIN Application */

/* LwIP 默认网卡（定义在 LWIP/App/lwip.c） */
extern struct netif gnetif;

/* FreeRTOS 栈溢出钩子：打印是哪个任务溢出后复位，避免“死机”无任何提示 */
void vApplicationStackOverflowHook(TaskHandle_t xTask, char *pcTaskName)
{
  static const char msg[] = "\r\n[FATAL] FreeRTOS stack overflow: ";
  extern UART_HandleTypeDef huart1;

  (void)xTask;
  LCD_Diag_Overflow(pcTaskName);   /* 存到复位不清零区，重启后屏上可见 */

  HAL_UART_Transmit(&huart1, (uint8_t*)msg, sizeof(msg) - 1, 100);
  if (pcTaskName != NULL) {
    HAL_UART_Transmit(&huart1, (uint8_t*)pcTaskName,
                      (uint16_t)strlen(pcTaskName), 100);
  }
  HAL_UART_Transmit(&huart1, (uint8_t*)"\r\n", 2, 100);
  NVIC_SystemReset();
}

/* ---- 开机复位原因（RCC->CSR）：用于判断“断网”是复位还是链路问题 ---- */
static uint8_t g_reset_cause = 0;   /* 1=IWDG 2=WWDG 3=SOFT 4=POR 5=PIN 6=BOR */

static const char *reset_cause_str(void)
{
  switch (g_reset_cause) {
    case 1: return "IWDG";   /* 看门狗：程序卡死/硬件异常 */
    case 2: return "WWDG";
    case 3: return "SOFT";   /* 软件复位（栈溢出钩子/NVIC_SystemReset） */
    case 4: return "POR";    /* 上电或掉电 */
    case 5: return "PIN";    /* 复位引脚 */
    case 6: return "BOR";    /* 低压复位：供电跌落/干扰 */
    default: return "?";
  }
}

static void read_reset_cause(void)
{
  uint32_t csr = RCC->CSR;

  if (csr & RCC_CSR_IWDGRSTF)      g_reset_cause = 1;
  else if (csr & RCC_CSR_WWDGRSTF) g_reset_cause = 2;
  else if (csr & RCC_CSR_SFTRSTF)  g_reset_cause = 3;
  else if (csr & RCC_CSR_PORRSTF)  g_reset_cause = 4;   /* 上电：POR 优先于 BOR */
  else if (csr & RCC_CSR_PINRSTF)  g_reset_cause = 5;
  else if (csr & RCC_CSR_BORRSTF)  g_reset_cause = 6;   /* 运行中掉压才会单独置位 */
  else                             g_reset_cause = 0;

  RCC->CSR |= RCC_CSR_RMVF;   /* 清除标志，避免下次误读 */
}

/* ---- 网络状态读取：DHCP 动态分配的本机地址 ---- */
static int net_ip_is_valid(void)
{
  return !ip4_addr_isany_val(*netif_ip4_addr(&gnetif));
}

static void net_get_ip_str(char *buf, uint16_t len)
{
  const ip4_addr_t *ip = netif_ip4_addr(&gnetif);

  if (ip4_addr_isany_val(*ip))
    snprintf(buf, len, "0.0.0.0");
  else
    ip4addr_ntoa_r(ip, buf, (int)len);
}

static void net_get_gw_str(char *buf, uint16_t len)
{
  const ip4_addr_t *gw = netif_ip4_gw(&gnetif);

  if (ip4_addr_isany_val(*gw))
    snprintf(buf, len, "0.0.0.0");
  else
    ip4addr_ntoa_r(gw, buf, (int)len);
}

/**
  * @brief  Startup task — runs after the scheduler has started.
  *         Initializes LwIP (which creates threads/semaphores),
  *         then deletes itself.
  */
void Startup_Task(void *argument)
{
  /* 读取上次运行的崩溃诊断（栈溢出任务/阶段/config.set），并清空供本次记录 */
  LCD_Diag_Init();

  /* 先记录本次复位原因，便于现场判断是复位还是链路/网络问题 */
  read_reset_cause();
  printf("RST:%s\r\n", reset_cause_str());

  IWDG->KR = 0xAAAA;   /* LwIP 初始化可能耗时 >5秒，先喂狗 */
  MX_LWIP_Init();
  IWDG->KR = 0xAAAA;   /* 初始化完成再喂一次 */

  /* 通知 TCP Server 任务：LwIP 已就绪 */
  osSemaphoreRelease(LwipReadySemaphore);

  /* 初始化 LCD（调度器已启动，FSMC 访问安全） */
  LCD_Init();

  /* 初始化触摸屏（XPT2046） */
  Touch_Init();

  /* 通知 LCD 刷新任务：LCD 已就绪 */
  osSemaphoreRelease(LcdUpdateSemaphore);

  /* LwIP + LCD init done, no longer needed */
  osThreadTerminate(StartupTaskHandle);
}

/**
  * @brief  LCD 刷新任务 — 根据 g_lcd_state 刷屏显示
  */

/* 闸门名称（文件级，按钮绘制与触摸任务共用） */
static const u8 *gate_names[RELAY_COUNT] = {
    (u8*)"\xD4\xA2\xC3\xC5\xD2\xBB",   /* 闸门一 */
    (u8*)"\xD4\xA2\xC3\xC5\xB6\xFE",   /* 闸门二 */
    (u8*)"\xD4\xA2\xC3\xC5\xC8\xFD",   /* 闸门三 */
    (u8*)"\xD4\xA2\xC3\xC5\xCB\xC4",   /* 闸门四 */
    (u8*)"\xD4\xA2\xC3\xC5\xCE\xE5",   /* 闸门五 */
    (u8*)"\xD4\xA2\xC3\xC5\xC1\xF9",   /* 闸门六 */
    (u8*)"\xD4\xA2\xC3\xC5\xC6\xDF",   /* 闸门七 */
    (u8*)"\xD4\xA2\xC3\xC5\xB0\xCB"    /* 闸门八 */
};

/* 绘制单个闸门按钮（触摸触发时局部刷新用） */
static void draw_gate_button(int i)
{
    u16 x = 8 + (i % 2) * 152;    /* 左列x=8, 右列x=160 */
    u16 y = 74 + (i / 2) * 38;    /* 行距38px, 4行: y=74/112/150/188 */
    u16 btn_color = g_relays[i].state ? GREEN : RED;
    u16 back_save = BACK_COLOR;

    /* 按钮背景：ON=绿 OFF=红（高35px） */
    LCD_Fill(x, y, x + 140, y + 35, btn_color);

    /* 文字空白像素用按钮色填充，避免盖出白块 */
    BACK_COLOR = btn_color;
    POINT_COLOR = g_relays[i].state ? BLACK : WHITE;
    LCD_ShowChinese(x + 4, y + 9, gate_names[i], POINT_COLOR);
    LCD_ShowString(x + 56, y + 9, 52, 16, 16,
                   (u8*)(g_relays[i].state ? "ON" : "OFF"));
    BACK_COLOR = back_save;
}

void LCD_Update_Task(void *argument)
{
  char line[40];
  
  for (;;)
  {
    /* LCD 尚未初始化完成（lcddev 尺寸为 0）时禁止刷屏，
       否则 LCD_Fill 会拿到 0xFFFF 边界而导致死循环 */
    if (lcddev.width == 0u || lcddev.height == 0u)
    {
      osDelay(100);
      continue;
    }

    /* 等待更新信号（由 TCP 任务或其他模块触发）
       2 秒超时兜底：DHCP 分配到 IP 后即使没有其他事件也能刷新屏幕 */
    osSemaphoreAcquire(LcdUpdateSemaphore, 2000);
    osDelay(50);  /* 防抖，等待多次更新合并 */
    
    /* 清空信号量，确保只处理最新一次 */
    osSemaphoreAcquire(LcdUpdateSemaphore, 0);

    /* ---- 绘制界面 ---- */
    LCD_Diag_Stage(20);   /* 阶段码：LCD 刷新开始 */
    /* 标题行 */
    BACK_COLOR = WHITE;
    POINT_COLOR = BLACK;
    LCD_Fill(0, 0, lcddev.width - 1, lcddev.height - 1, WHITE);
    
    /* 顶部标题 */
    POINT_COLOR = BLUE;
    LCD_ShowChinese(4, 4, (u8*)"\xD6\xC7\xD3\xF9\xB0\xB2\xC0\xBC", POINT_COLOR);
    LCD_ShowString(68, 4, 60, 20, 16, (u8*)"RTU");
    LCD_ShowChinese(104, 4, (u8*)"\xB2\xC9\xBC\xAF\xD6\xD5\xB6\xCB", POINT_COLOR);
    
    /* 分隔线 */
    POINT_COLOR = GRAY;
    LCD_DrawLine(0, 24, lcddev.width - 1, 24);
    
    /* MQTT 连接状态 */
    POINT_COLOR = (g_lcd_state.tcp_connected) ? GREEN : RED;
    snprintf(line, sizeof(line), "MQTT Server: %s",
             g_lcd_state.tcp_connected ? g_lcd_state.client_ip : "Disconnected");
    LCD_ShowString(4, 28, 300, 16, 16, (u8*)line);
    
    /* 分隔线 */
    POINT_COLOR = GRAY;
    LCD_DrawLine(0, 48, lcddev.width - 1, 48);
    
    /* 闸门状态 — 标题 */
    POINT_COLOR = BLACK;
    LCD_ShowChinese(4, 52, (u8*)"\xD4\xA2\xC3\xC5\xD7\xB4\xCC\xAC", POINT_COLOR);  /* 闸门状态 */
    
    /* 8路闸门按钮：2列布局，既是状态显示也是触摸按钮 */
    for (int i = 0; i < RELAY_COUNT; i++)
    {
      draw_gate_button(i);
    }
    
    /* 分隔线 */
    POINT_COLOR = GRAY;
    LCD_DrawLine(0, 232, lcddev.width - 1, 232);
    
    /* 传感器数据 — 每行独立，数值用醒目的 CYAN 色 */
    POINT_COLOR = BLACK;
    LCD_ShowChinese(4, 238, (u8*)"\xB4\xAB\xB8\xD0\xC6\xF7", POINT_COLOR);  /* 传感器 */
    LCD_ShowString(68, 238, 16, 16, 16, (u8*)":");

    u16 y_sensor = 258;
    #define SENSOR_LINE_GAP  20

    /* Level */
    POINT_COLOR = GRAY;
    LCD_ShowString(4, y_sensor, 80, 16, 16, (u8*)"Level");
    if (g_sensors[SENSOR_LEVEL].valid) {
        POINT_COLOR = BLUE;
        snprintf(line, sizeof(line), "%.1f cm", (double)g_sensors[SENSOR_LEVEL].value);
    } else {
        POINT_COLOR = GRAY;
        snprintf(line, sizeof(line), "--");
    }
    LCD_ShowString(68, y_sensor, 120, 16, 16, (u8*)line);
    y_sensor += SENSOR_LINE_GAP;

    /* Temp */
    POINT_COLOR = GRAY;
    LCD_ShowString(4, y_sensor, 80, 16, 16, (u8*)"Temp");
    if (g_sensors[SENSOR_TEMP].valid) {
        POINT_COLOR = BLUE;
        snprintf(line, sizeof(line), "%.1f C", (double)g_sensors[SENSOR_TEMP].value);
    } else {
        POINT_COLOR = GRAY;
        snprintf(line, sizeof(line), "--");
    }
    LCD_ShowString(68, y_sensor, 120, 16, 16, (u8*)line);
    y_sensor += SENSOR_LINE_GAP;

    /* pH */
    POINT_COLOR = GRAY;
    LCD_ShowString(4, y_sensor, 80, 16, 16, (u8*)"pH");
    if (g_sensors[SENSOR_PH].valid) {
        POINT_COLOR = BLUE;
        snprintf(line, sizeof(line), "%.2f", (double)g_sensors[SENSOR_PH].value);
    } else {
        POINT_COLOR = GRAY;
        snprintf(line, sizeof(line), "--");
    }
    LCD_ShowString(68, y_sensor, 120, 16, 16, (u8*)line);
    y_sensor += SENSOR_LINE_GAP;

    /* ORP */
    POINT_COLOR = GRAY;
    LCD_ShowString(4, y_sensor, 80, 16, 16, (u8*)"ORP");
    if (g_sensors[SENSOR_ORP].valid) {
        POINT_COLOR = BLUE;
        snprintf(line, sizeof(line), "%+.0f mV", (double)g_sensors[SENSOR_ORP].value);
    } else {
        POINT_COLOR = GRAY;
        snprintf(line, sizeof(line), "--");
    }
    LCD_ShowString(68, y_sensor, 120, 16, 16, (u8*)line);

    /* ---- 网络状态：DHCP 动态分配的本机 IP ---- */
    POINT_COLOR = GRAY;
    LCD_DrawLine(0, 342, lcddev.width - 1, 342);

    {
        char ip_str[16];
        char gw_str[16];
        char broker_ip[16];
        uint16_t broker_port = 0;
        int ip_valid = net_ip_is_valid();

        net_get_ip_str(ip_str, sizeof(ip_str));
        net_get_gw_str(gw_str, sizeof(gw_str));

        /* DHCP 分配到的 IPv4 地址：24 号大字，未分配时灰色 */
        POINT_COLOR = ip_valid ? BLUE : GRAY;
        snprintf(line, sizeof(line), "IP:%s", ip_str);
        LCD_ShowString(4, 352, 300, 24, 24, (u8*)line);

        /* DHCP 状态 + 网关 */
        if (ip_valid) {
            POINT_COLOR = GRAY;
            snprintf(line, sizeof(line), "DHCP OK  GW:%s", gw_str);
        } else {
            POINT_COLOR = RED;
            snprintf(line, sizeof(line), "DHCP: waiting...");
        }
        LCD_ShowString(4, 382, 300, 16, 16, (u8*)line);

        /* 当前 MQTT Broker 服务器（读 MQTT 模块缓存，不在 UI 任务里解析 RTC） */
        MQTT_GetBrokerInfo(broker_ip, sizeof(broker_ip), &broker_port);
        POINT_COLOR = g_lcd_state.tcp_connected ? GREEN : GRAY;
        snprintf(line, sizeof(line), "MQTT:%s:%u", broker_ip, (unsigned)broker_port);
        LCD_ShowString(4, 400, 300, 16, 16, (u8*)line);

        /* 现场诊断：复位原因 + 链路状态 + 上次崩溃信息 / MQTT 断开原因码 */
        {
            int disc_reason = 0;
            uint32_t disc_cnt = 0;
            const LCD_DiagView_t *dv = LCD_Diag_View();

            MQTT_GetStats(&disc_reason, &disc_cnt);

            POINT_COLOR = GRAY;
            snprintf(line, sizeof(line), "RST:%s  LINK:%s",
                     reset_cause_str(), netif_is_link_up(&gnetif) ? "UP" : "DOWN");
            LCD_ShowString(4, 418, 300, 16, 16, (u8*)line);

            if (dv->ovf_count > 0) {
                /* 上次运行发生过栈溢出（若为强电干扰导致的误报，会显示这里的任务名） */
                POINT_COLOR = RED;
                snprintf(line, sizeof(line), "OVF:%s STG:%lu",
                         dv->ovf_task, (unsigned long)dv->crash_stage);
            } else if (dv->cfg_reset) {
                POINT_COLOR = RED;
                snprintf(line, sizeof(line), "CFG:SET STG:%lu",
                         (unsigned long)dv->crash_stage);
            } else {
                POINT_COLOR = g_lcd_state.tcp_connected ? GRAY : RED;
                snprintf(line, sizeof(line), "MQTT err:%d dn:%lu",
                         disc_reason, (unsigned long)disc_cnt);
            }
            LCD_ShowString(4, 436, 300, 16, 16, (u8*)line);
        }
    }

    /* 底部 — 最近更新时间戳 */
    POINT_COLOR = GRAY;
    LCD_ShowChinese(4, lcddev.height - 20,
        (u8*)"\xD7\xEE\xBD\xFC\xB8\xFC\xD0\xC2\xCA\xB1\xBC\xE4\xB4\xC1",
        POINT_COLOR);  /* 最近更新时间戳 */
    snprintf(line, sizeof(line), ": %lu", g_lcd_state.last_update_tick);
    LCD_ShowString(116, lcddev.height - 20, 90, 16, 16, (u8*)line);

    /* 调试：显示触摸坐标（验证触摸链路，确认后删除） */
    snprintf(line, sizeof(line), "T:%u,%u", touch_x, touch_y);
    LCD_ShowString(210, lcddev.height - 20, 110, 16, 16, (u8*)line);
    LCD_Diag_Stage(21);   /* 阶段码：LCD 刷新完成 */
  }
}

/**
  * @brief  触摸按钮表 — 与 LCD_Update_Task 绘制的闸门按钮区域一致
  */
typedef struct {
    u16      x, y, w, h;   /* 按钮矩形 */
    uint8_t  relay_id;     /* 对应继电器 id (1~8) */
} TouchButton_t;

static const TouchButton_t g_touch_buttons[RELAY_COUNT] = {
    { 8,   74, 140, 35, 1 },
    { 160, 74, 140, 35, 2 },
    { 8,   112, 140, 35, 3 },
    { 160, 112, 140, 35, 4 },
    { 8,   150, 140, 35, 5 },
    { 160, 150, 140, 35, 6 },
    { 8,   188, 140, 35, 7 },
    { 160, 188, 140, 35, 8 },
};

/**
  * @brief  触摸扫描任务 — 检测点击（按下→松开），命中按钮则切换闸门
  */
void Touch_Task(void *argument)
{
    (void)argument;

    uint8_t  prev_down = 0;     /* 上一帧是否按下 */
    uint16_t down_x = 0, down_y = 0;  /* 按下时坐标 */

    osDelay(600);               /* 等触摸/LCD 初始化完成 */

    for (;;)
    {
        LCD_Diag_Stage(40);   /* 阶段码：触摸扫描 */
        uint8_t down = Touch_Scan();

        if (down && !prev_down) {
            /* 按下沿：记录坐标 */
            down_x = touch_x;
            down_y = touch_y;
        }

        if (!down && prev_down) {
            /* 松开沿：命中检测（按钮区域与绘制一致） */
            for (int i = 0; i < RELAY_COUNT; i++) {
                if (down_x >= g_touch_buttons[i].x &&
                    down_x <  g_touch_buttons[i].x + g_touch_buttons[i].w &&
                    down_y >= g_touch_buttons[i].y &&
                    down_y <  g_touch_buttons[i].y + g_touch_buttons[i].h) {
                    uint8_t id = g_touch_buttons[i].relay_id;
                    Relay_SetState(id, !Relay_GetState(id));  /* 点击切换 */
                    g_lcd_state.last_update_tick = HAL_GetTick();
                    draw_gate_button(id - 1);   /* 立即局部刷新该按钮 */
                    osSemaphoreRelease(LcdUpdateSemaphore);  /* 全屏兜底刷新 */
                    break;
                }
            }
        }

        prev_down = down;
        osDelay(15);
    }
}
/* USER CODE END Application */

