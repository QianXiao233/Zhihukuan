/**
 * HUSKYLENS 2 驱动实现（ESP-IDF 原生，最小子集）
 */
#include "huskylens.h"

#include <string.h>

#include "driver/i2c_master.h"
#include "driver/gpio.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "shared/boat_controller_config.h"

static const char *TAG = "BOAT_HUSKY";

#define HUSKY_I2C_TIMEOUT_MS   100
#define HUSKY_READ_CHUNK       16      /* 与库一致：每次读 16 字节 */
#define HUSKY_WRITE_CHUNK      16      /* 与库一致：每包 16 字节 */
#define HUSKY_MAX_BLOCKS       8
#define HUSKY_RX_BUF           512

/* ---------------- 传输层 ---------------- */
static i2c_master_bus_handle_t s_bus;
static i2c_master_dev_handle_t s_dev;
static bool s_ready;
static bool s_bus_inited;      /* I2C 总线只允许创建一次 */
static bool s_probe_warned;    /* 探测失败只提示一次，避免重试刷屏 */

/* ---------------- 接收状态机 ---------------- */
static uint8_t s_rx[HUSKY_RX_BUF];
static size_t s_rx_len;
static size_t s_expect_len;          /* 期望的整帧长度（含校验） */

/* ---------------- 结果缓存 ---------------- */
static husky_block_t s_blocks[HUSKY_MAX_BLOCKS];
static int s_block_count;
static bool s_got_any;

/* ---------------- 帧分发 ----------------
 * 二哈除了应答命令，还会周期性地主动发送心跳帧（命令 0x1A，数据含
 * 一个 IEEE754 浮点 + 4 字节计数器，实测约每 150 ms 一帧）。
 * 因此"收到任意完整帧"不等于"收到了本次命令的应答" —— 必须按命令号匹配，
 * 否则会把心跳误判成 KNOCK/SET_ALGORITHM 的应答。
 */
static volatile uint8_t  s_last_cmd;      /* 最近一次解析出的帧命令 */
static volatile bool     s_args_ok;       /* 最近一次 RETURN_ARGS 的 retValue == 0 */
static volatile uint32_t s_frame_seq;     /* 完整帧序号 */

/* ================= 传输层 ================= */

/* 前向声明：错误恢复流程需要重建总线，而定义在文件后部 */
static bool husky_transport_init(void);
static void rx_feed(uint8_t b);

/* 错误日志限流：I2C 出错后每 100 ms 都会重试，不能每次都打日志 */
static uint32_t s_err_log_ms;
static uint32_t s_err_count;
static bool     s_transport_down;    /* 总线异常后置位，由恢复流程清除 */

static void log_i2c_error_once(const char *op, esp_err_t err)
{
    uint32_t t = xTaskGetTickCount() * portTICK_PERIOD_MS;
    s_err_count++;
    if (t - s_err_log_ms >= 5000) {
        s_err_log_ms = t;
        ESP_LOGW(TAG, "I2C %s 失败: %s (累计 %lu 次)",
                 op, esp_err_to_name(err), (unsigned long)s_err_count);
    }
}

/**
 * 重新初始化 I2C 总线与设备句柄。
 *
 * 为什么需要：I2C 一旦出现 NACK/时序异常，ESP-IDF 驱动会让后续调用持续返回
 * ESP_ERR_INVALID_STATE 且**不会自行恢复**（实测运行十几秒后会进入这种状态）。
 * 实测最有效的恢复方式是把总线删掉重建。
 */
static bool i2c_recover(void)
{
    ESP_LOGW(TAG, "尝试重建 I2C 总线以恢复通信");

    if (s_dev) {
        i2c_master_bus_rm_device(s_dev);
        s_dev = NULL;
    }
    if (s_bus) {
        i2c_del_master_bus(s_bus);
        s_bus = NULL;
    }
    s_bus_inited = false;
    s_transport_down = false;
    s_err_count = 0;

    /* 交给传输层重建 */
    if (!husky_transport_init()) {
        ESP_LOGE(TAG, "I2C 重建失败");
        return false;
    }
    /* 重建后需要重新握手 */
    s_ready = false;
    ESP_LOGI(TAG, "I2C 总线已重建，需重新握手");
    return true;
}

static bool i2c_write_frame(const uint8_t *frame, size_t len)
{
    size_t offset = 0;
    while (offset < len) {
        size_t chunk = len - offset;
        if (chunk > HUSKY_WRITE_CHUNK) chunk = HUSKY_WRITE_CHUNK;
        esp_err_t err = i2c_master_transmit(s_dev, frame + offset, chunk, HUSKY_I2C_TIMEOUT_MS);
        if (err != ESP_OK) {
            log_i2c_error_once("写", err);
            s_transport_down = true;
            return false;
        }
        offset += chunk;
    }
    return true;
}

static void rx_feed(uint8_t b);

/** 诊断统计：仅在"最终放弃握手"时输出，避免每次重试都刷屏 */
static uint32_t s_diag_read_ok;
static uint32_t s_diag_read_fail;
static uint32_t s_diag_bytes;
static uint32_t s_diag_frames;
static uint32_t s_diag_bad_sum;
static uint8_t  s_diag_first[16];
static bool     s_diag_first_valid;
static bool     s_diag_reported;

/** 从 I2C 读一批字节喂给状态机，返回是否已收到任何有效帧 */
static bool i2c_drain_once(void)
{
    uint8_t buf[HUSKY_READ_CHUNK];
    esp_err_t err = i2c_master_receive(s_dev, buf, sizeof(buf), HUSKY_I2C_TIMEOUT_MS);
    if (err != ESP_OK) {
        s_diag_read_fail++;
        log_i2c_error_once("读", err);
        s_transport_down = true;
        return false;
    }
    s_diag_read_ok++;
    s_diag_bytes += sizeof(buf);
    if (!s_diag_first_valid) {
        memcpy(s_diag_first, buf, sizeof(s_diag_first));
        s_diag_first_valid = true;
    }
    for (size_t i = 0; i < sizeof(buf); i++) rx_feed(buf[i]);
    return s_got_any;
}

/** 打印诊断信息（仅在最终放弃握手时调用） */
void huskylens_dump_diagnostics(void)
{
    if (s_diag_reported) return;   /* 只报一次 */
    s_diag_reported = true;

    ESP_LOGW(TAG, "[诊断] 读成功=%lu 读失败=%lu 字节=%lu 完整帧=%lu 校验失败=%lu",
             (unsigned long)s_diag_read_ok, (unsigned long)s_diag_read_fail,
             (unsigned long)s_diag_bytes, (unsigned long)s_diag_frames,
             (unsigned long)s_diag_bad_sum);
    if (s_diag_first_valid) {
        ESP_LOGW(TAG, "[诊断] 首批原始字节: %02X %02X %02X %02X %02X %02X %02X %02X "
                      "%02X %02X %02X %02X %02X %02X %02X %02X",
                 s_diag_first[0], s_diag_first[1], s_diag_first[2], s_diag_first[3],
                 s_diag_first[4], s_diag_first[5], s_diag_first[6], s_diag_first[7],
                 s_diag_first[8], s_diag_first[9], s_diag_first[10], s_diag_first[11],
                 s_diag_first[12], s_diag_first[13], s_diag_first[14], s_diag_first[15]);
    }
}

/* ================= 状态机 ================= */

static void rx_reset(void)
{
    s_rx_len = 0;
    s_expect_len = 0;
}

/**
 * 处理一个字节。
 * 帧布局: [0]=0x55 [1]=0xAA [2]=CMD [3]=AlgoID [4]=Len [5..]=Data [5+Len]=校验
 * 整帧长度 = 6 + Len
 */
static void rx_feed(uint8_t b)
{    if (s_rx_len == 0) {
        if (b != 0x55) return;          /* 等待帧头 */
        s_rx[s_rx_len++] = b;
        return;
    }
    if (s_rx_len == 1) {
        if (b != 0xAA) { rx_reset(); if (b == 0x55) { s_rx[s_rx_len++] = b; } return; }
        s_rx[s_rx_len++] = b;
        return;
    }

    if (s_rx_len >= HUSKY_RX_BUF) { rx_reset(); return; }
    s_rx[s_rx_len++] = b;

    /* 收满头部即可算出整帧长度 */
    if (s_rx_len == 5) {
        s_expect_len = 6 + s_rx[4];
        if (s_expect_len > HUSKY_RX_BUF) { rx_reset(); return; }
    }

    if (s_expect_len && s_rx_len == s_expect_len) {
        /* 校验：从 [0] 累加到 [4+Len]，即整帧除最后一个字节 */
        uint8_t sum = 0;
        for (size_t i = 0; i + 1 < s_expect_len; i++) sum += s_rx[i];
        if (sum != s_rx[s_expect_len - 1]) {
            s_diag_bad_sum++;
            ESP_LOGW(TAG, "校验失败: 计算 0x%02X 收到 0x%02X", sum, s_rx[s_expect_len - 1]);
            rx_reset();
            return;
        }

        uint8_t cmd = s_rx[2];
        uint8_t len = s_rx[4];
        const uint8_t *data = &s_rx[5];

        s_diag_frames++;
        s_last_cmd = cmd;
        s_frame_seq++;

        if (cmd == HUSKY_CMD_RETURN_ARGS) {
            /* 协议：RETURN_ARGS 数据段 [0]=totalIntArgs [1]=retValue，0 表示成功 */
            s_args_ok = (len >= 2 && data[1] == 0);
        } else if (cmd == HUSKY_CMD_RETURN_INFO) {
            /* 新一轮结果开始：清空上一轮块 */
            s_block_count = 0;
            s_got_any = true;
        } else if (cmd == HUSKY_CMD_RETURN_BLOCKS && len >= 14) {
            if (s_block_count < HUSKY_MAX_BLOCKS) {
                husky_block_t *blk = &s_blocks[s_block_count++];
                blk->id       = data[0];
                blk->algo_id  = data[1];
                /* 协议为小端 int16 */
                blk->x_center = (int16_t)(data[2] | (data[3] << 8));
                blk->y_center = (int16_t)(data[4] | (data[5] << 8));
                blk->width    = (int16_t)(data[6] | (data[7] << 8));
                blk->height   = (int16_t)(data[8] | (data[9] << 8));
            }
            s_got_any = true;
        }
        rx_reset();
    }
}

/* ================= 协议层 ================= */

/** 组装并发送一帧 */
static bool send_command(uint8_t cmd, husky_algorithm_t algo, const uint8_t *data, uint8_t len)
{
    uint8_t frame[64];
    if ((size_t)len + 6 > sizeof(frame)) return false;

    frame[0] = 0x55;
    frame[1] = 0xAA;
    frame[2] = cmd;
    frame[3] = (uint8_t)algo;
    frame[4] = len;
    if (len && data) memcpy(&frame[5], data, len);

    uint8_t sum = 0;
    for (size_t i = 0; i < (size_t)len + 5; i++) sum += frame[i];
    frame[5 + len] = sum;

    return i2c_write_frame(frame, (size_t)len + 6);
}

/**
 * 发命令后等待"指定命令号"的应答帧。
 *
 * 必须按命令号匹配：二哈会主动发心跳帧，若只判断"收到了完整帧"就会把心跳
 * 误当成应答（这正是最初握手判定错误的原因）。
 *
 * @param expect_cmd   期望的应答命令号
 * @param require_ok   仅对 RETURN_ARGS 有意义：是否要求 retValue == 0
 */
static bool wait_for_command(uint8_t expect_cmd, bool require_ok, uint32_t timeout_ms)
{
    uint32_t start = xTaskGetTickCount() * portTICK_PERIOD_MS;

    while ((xTaskGetTickCount() * portTICK_PERIOD_MS - start) < timeout_ms) {
        uint32_t seq_before = s_frame_seq;
        i2c_drain_once();

        if (s_frame_seq != seq_before && s_last_cmd == expect_cmd) {
            if (expect_cmd == HUSKY_CMD_RETURN_ARGS && require_ok) return s_args_ok;
            return true;
        }
        vTaskDelay(pdMS_TO_TICKS(2));
    }
    return false;
}

/**
 * 确保 I2C 总线与设备句柄已创建。
 *
 * 注意：i2c_new_master_bus() 对一个端口只能成功一次，重复调用会返回
 * ESP_ERR_INVALID_STATE（"bus id has already been acquired"）。所以这里用
 * s_bus_inited 守卫，保证只初始化一次 —— 否则上层重试握手时会刷屏报错。
 */
static bool husky_transport_init(void)
{
    if (s_bus_inited) return true;

    i2c_master_bus_config_t bus_cfg = {
        .i2c_port = I2C_NUM_0,
        .sda_io_num = HUSKY_I2C_SDA_GPIO,
        .scl_io_num = HUSKY_I2C_SCL_GPIO,
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
    };
    esp_err_t err = i2c_new_master_bus(&bus_cfg, &s_bus);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "I2C 总线初始化失败: %s", esp_err_to_name(err));
        return false;
    }

    i2c_device_config_t dev_cfg = {
        .dev_addr_length = I2C_ADDR_BIT_LEN_7,
        .device_address = HUSKY_I2C_ADDR,
        .scl_speed_hz = HUSKY_I2C_FREQ_HZ,
    };
    err = i2c_master_bus_add_device(s_bus, &dev_cfg, &s_dev);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "添加 I2C 设备失败: %s", esp_err_to_name(err));
        return false;
    }

    s_bus_inited = true;
    return true;
}

bool huskylens_begin(void)
{
    if (s_ready) return true;              /* 已握手成功，不重复 */

    /* 总线曾出错则先重建，否则后续调用会一直返回 ESP_ERR_INVALID_STATE */
    if (s_transport_down) {
        if (!i2c_recover()) return false;
    }

    if (!husky_transport_init()) return false;

    /* 探测设备是否存在，避免后续命令在无设备时静默失败。
       失败只提示一次，避免上层重试时刷屏。 */
    esp_err_t err = i2c_master_probe(s_bus, HUSKY_I2C_ADDR, HUSKY_I2C_TIMEOUT_MS);
    if (err != ESP_OK) {
        if (!s_probe_warned) {
            s_probe_warned = true;
            ESP_LOGW(TAG, "未探测到 HUSKYLENS（地址 0x%02X）: %s —— 请确认二哈已上电、"
                          "Protocol Type 设为 I2C、且 SDA/SCL 接线正确",
                     HUSKY_I2C_ADDR, esp_err_to_name(err));
        }
        return false;
    }

    /* KNOCK：告诉二哈主机是大内存 MCU，Data 10 字节，第 0 字节 boardType=1。
       库的 knock() 会重试 5 次，这里同样重试，避免单次丢帧导致握手失败。 */
    uint8_t knock[10] = {1};
    bool ok = false;
    for (int attempt = 0; attempt < 5 && !ok; attempt++) {
        rx_reset();
        if (!send_command(HUSKY_CMD_KNOCK, ALGO_ANY, knock, sizeof(knock))) {
            ESP_LOGE(TAG, "KNOCK 发送失败");
            break;
        }
        ok = wait_for_command(HUSKY_CMD_RETURN_ARGS, true, 300);
    }

    if (ok) {
        s_ready = true;
        ESP_LOGI(TAG, "HUSKYLENS 2 握手成功");
    }
    /* 失败时不在这里打日志：上层会重试，只在最终放弃时调用
       huskylens_dump_diagnostics()，避免每次重试都刷屏。 */
    return ok;
}

bool huskylens_switch_algorithm(husky_algorithm_t algo)
{
    if (!s_ready) return false;

    /* SET_ALGORITHM：Data 10 字节，第 0 字节为目标算法 ID */
    uint8_t data[10] = {0};
    data[0] = (uint8_t)algo;

    /* 二哈切换算法需要时间，且刚握手完可能还没准备好接收。
       实测单次发送常失败，所以加延时 + 重试（与原库 retry 语义一致）。 */
    bool ok = false;
    for (int attempt = 0; attempt < 3 && !ok; attempt++) {
        vTaskDelay(pdMS_TO_TICKS(150));
        rx_reset();
        if (!send_command(HUSKY_CMD_SET_ALGORITHM, algo, data, sizeof(data))) break;
        ok = wait_for_command(HUSKY_CMD_RETURN_ARGS, true, 800);
    }

    ESP_LOGI(TAG, "切换算法 %d %s", (int)algo, ok ? "成功" : "失败");
    return ok;
}

bool huskylens_get_result(husky_algorithm_t algo)
{
    if (!s_ready) return false;

    s_got_any = false;
    s_block_count = 0;

    /* GET_RESULT：Data Length = 0 */
    if (!send_command(HUSKY_CMD_GET_RESULT, algo, NULL, 0)) return false;

    /* 返回序列为 RETURN_INFO + RETURN_BLOCKS... + RETURN_ARROWS...
       固定读若干批（每批 16 字节）覆盖整轮结果。
       不按"收到 INFO 就退出"，因为块数据在 INFO 之后才到。 */
    for (int i = 0; i < 8; i++) {
        if (!i2c_drain_once() && i > 0 && s_got_any) break;
        vTaskDelay(pdMS_TO_TICKS(3));
    }

    return s_got_any;
}

int huskylens_block_count(void) { return s_block_count; }

bool huskylens_get_block(int index, husky_block_t *out)
{
    if (index < 0 || index >= s_block_count || out == NULL) return false;
    *out = s_blocks[index];
    return true;
}

bool huskylens_is_ready(void) { return s_ready; }
