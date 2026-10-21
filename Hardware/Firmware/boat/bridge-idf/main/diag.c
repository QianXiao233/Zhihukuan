/**
 * 诊断实现：芯片温度 + CPU 占用
 */
#include "diag.h"

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "driver/temperature_sensor.h"

#if CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS
#include "freertos/idf_additions.h"
#define HAS_RUNTIME_STATS 1
#else
#define HAS_RUNTIME_STATS 0
#endif

static const char *TAG = "BRIDGE_DIAG";

#define DIAG_INTERVAL_MS   5000
#define TSENS_MIN_C        (-10)
#define TSENS_MAX_C        (80)

static temperature_sensor_handle_t s_tsens;
static bool s_tsens_ok;
static uint32_t s_last_ms;

void diag_init(void)
{
    temperature_sensor_config_t cfg = TEMPERATURE_SENSOR_CONFIG_DEFAULT(TSENS_MIN_C, TSENS_MAX_C);
    esp_err_t err = temperature_sensor_install(&cfg, &s_tsens);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "温度传感器安装失败(%s)，跳过温度统计", esp_err_to_name(err));
        return;
    }
    err = temperature_sensor_enable(s_tsens);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "温度传感器使能失败(%s)，跳过温度统计", esp_err_to_name(err));
        return;
    }
    s_tsens_ok = true;

#if !HAS_RUNTIME_STATS
    ESP_LOGW(TAG, "未开启 CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS，CPU 占用统计不可用");
#endif
}

bool diag_get_temperature(float *out_celsius)
{
    if (!s_tsens_ok || out_celsius == NULL) return false;
    return temperature_sensor_get_celsius(s_tsens, out_celsius) == ESP_OK;
}

bool diag_get_cpu_load(uint32_t *out_cpu0, uint32_t *out_cpu1)
{
#if HAS_RUNTIME_STATS
    if (out_cpu0) *out_cpu0 = 100 - (uint32_t)ulTaskGetIdleRunTimePercentForCore(0);
    if (out_cpu1) *out_cpu1 = 100 - (uint32_t)ulTaskGetIdleRunTimePercentForCore(1);
    return true;
#else
    (void)out_cpu0;
    (void)out_cpu1;
    return false;
#endif
}

void diag_tick(void)
{
    uint32_t now = xTaskGetTickCount() * portTICK_PERIOD_MS;
    if (now - s_last_ms < DIAG_INTERVAL_MS) return;
    s_last_ms = now;

    float celsius = 0.0f;
    if (!diag_get_temperature(&celsius)) return;

    uint32_t cpu0 = 0, cpu1 = 0;
    if (diag_get_cpu_load(&cpu0, &cpu1)) {
        ESP_LOGI(TAG, "[诊断] 芯片结温 %.1f °C | CPU0 占用 %lu%% | CPU1 占用 %lu%%",
                 celsius, (unsigned long)cpu0, (unsigned long)cpu1);
    } else {
        ESP_LOGI(TAG, "[诊断] 芯片结温 %.1f °C", celsius);
    }
}
