/**
 * HUSKYLENS 2 驱动（ESP-IDF 原生实现，最小子集）
 *
 * 为什么不直接用 DFRobot_HuskylensV2 库：
 *   该库大量依赖 Arduino 专有类型（String / Stream / TwoWire），
 *   在 ESP-IDF 下移植需要重写协议层。而船端只用 5 个 API
 *   （begin / switchAlgorithm / getResult / available / popCachedResult），
 *   所以这里按官方协议文档直接实现这个子集，约 300 行，无外部依赖。
 *
 * 协议（来自 HuskyLens2_Protocol_CN.md，并与库源码逐字节核对）：
 *   帧: [0]=0x55 [1]=0xAA [2]=CMD [3]=AlgoID [4]=Len [5..4+Len]=Data [5+Len]=校验
 *   校验 = 从 [0] 累加到 [4+Len]（不含校验字节本身），取低 8 位
 *
 * 传输：
 *   I2C  —— 写：把整帧按 16 字节分包发给 0x50；读：直接读 16 字节（不发寄存器地址）
 *   UART —— 同一条线上的字节流
 *
 * 用法（与 Arduino 版一致）：
 *   1. huskylens_begin()           握手（KNOCK）
 *   2. huskylens_switch_algorithm(ALGO_OBJECT_TRACKING)
 *   3. 主循环：huskylens_get_result() 拉取；再用 huskylens_block_count() /
 *      huskylens_get_block() 取结果
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* 协议命令 */
#define HUSKY_CMD_KNOCK            0x00
#define HUSKY_CMD_GET_RESULT       0x01
#define HUSKY_CMD_SET_ALGORITHM    0x0A
#define HUSKY_CMD_RETURN_ARGS      0x1A
#define HUSKY_CMD_RETURN_INFO      0x1B
#define HUSKY_CMD_RETURN_BLOCKS    0x1C
#define HUSKY_CMD_RETURN_ARROWS    0x1D

/* 算法 ID（来自协议文档"算法ID"表） */
typedef enum {
    ALGO_ANY                  = 0,
    ALGO_FACE_RECOGNITION     = 1,
    ALGO_OBJECT_RECOGNITION   = 2,
    ALGO_OBJECT_TRACKING      = 3,
    ALGO_COLOR_RECOGNITION    = 4,
    ALGO_OBJECT_CLASSIFICATION = 5,
    ALGO_SELF_LEARNING        = 6,
    ALGO_SEGMENT              = 7,
    ALGO_HAND_RECOGNITION     = 8,
    ALGO_POSE_RECOGNITION     = 9,
    ALGO_LICENSE_RECOGNITION  = 10,
    ALGO_OCR_RECOGNITION      = 11,
    ALGO_LINE_TRACKING        = 12,
    ALGO_EMOTION_RECOGNITION  = 13,
    ALGO_GAZE_RECOGNITION     = 14,
    ALGO_FACE_ORIENTATION     = 15,
    ALGO_TAG_RECOGNITION      = 16,
    ALGO_BARCODE_RECOGNITION  = 17,
    ALGO_QRCODE_RECOGNITION   = 18,
    ALGO_FALLDOWN_RECOGNITION = 19,
} husky_algorithm_t;

/** 检测块（对应协议 RETURN_BLOCKS 的固定字段部分） */
typedef struct {
    uint8_t id;
    uint8_t algo_id;
    int16_t x_center;
    int16_t y_center;
    int16_t width;
    int16_t height;
} husky_block_t;

/**
 * @brief 初始化并握手
 * @return true 表示二哈在线且握手成功
 */
bool huskylens_begin(void);

/** @brief 切换算法，成功后内部记录当前算法 */
bool huskylens_switch_algorithm(husky_algorithm_t algo);

/**
 * @brief 拉取一次结果（发送 GET_RESULT 并解析返回的帧序列）
 * @param algo 期望的算法 ID
 * @return true 表示收到有效的 RETURN_INFO/block 响应
 */
bool huskylens_get_result(husky_algorithm_t algo);

/** @brief 最近一次结果中的块数量 */
int huskylens_block_count(void);

/** @brief 取第 index 个块，越界返回 false */
bool huskylens_get_block(int index, husky_block_t *out);

/** @brief 二哈是否曾成功握手 */
bool huskylens_is_ready(void);

/**
 * @brief 输出通信诊断信息（读次数/字节数/完整帧数/校验失败数 + 首批原始字节）
 *
 * 仅在**最终放弃握手**时调用一次。用于区分"完全没数据"（接线/供电/协议类型）
 * 与"有数据但格式不符"（协议实现问题）。
 */
void huskylens_dump_diagnostics(void);
