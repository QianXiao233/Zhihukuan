/**
 * ESP32-S3 桥接板固件
 * 功能：
 * 1. 电脑有指令 -> 通过 ESP-NOW 发给 DFR1063
 * 2. 电脑无指令 -> 每50ms轮询一次，保持链路活跃
 * 3. DFR1063 回包 -> 通过 USB 串口转给电脑
 */

#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_idf_version.h>

#include "../boat_config.h"   // 对端 MAC / 信道统一由此文件提供

// ==================== 配置 ====================
// 船载 DFR1063 的 ESP-NOW MAC，定义见 arduino-reference/boat_config.h
uint8_t dfr1063MAC[6];
const long SERIAL_BAUD = 115200;
const unsigned long POLL_INTERVAL_MS = 50;
const unsigned long HOST_COMMAND_TIMEOUT_MS = 300;
const uint8_t COMMAND_HEADER[] = {0xA5, 0x5A};
const uint8_t STATUS_HEADER[] = {0x5A, 0xA5};

// ==================== 数据结构 ====================
typedef struct struct_message {
    float boat_x, boat_y, boat_heading;
    float target_x, target_y;
    uint8_t mission_state;
    uint8_t release_flag;
    int16_t manual_throttle;
    int16_t manual_steer;
} __attribute__((packed)) GroundToBoat;

typedef struct struct_status {
    float boat_heading;
    int left_motor_speed;
    int right_motor_speed;
    uint8_t target_detected;
    int local_target_x;
    int local_target_y;
    float estimated_dist_m;
    uint8_t emergency_mode;
} BoatToGround;

GroundToBoat sendData;
BoatToGround recvData;
volatile bool pendingStatusReady = false;
BoatToGround pendingStatus;
portMUX_TYPE statusMux = portMUX_INITIALIZER_UNLOCKED;

static_assert(sizeof(GroundToBoat) == 26, "GroundToBoat layout must be 26 bytes");
static_assert(sizeof(BoatToGround) == 32, "BoatToGround layout must be 32 bytes");

bool hasPendingCommand = false;
unsigned long lastPollTime = 0;
unsigned long lastCommandTime = 0;
unsigned long lastSendErrorPrint = 0;

void readSerialCommands() {
    static uint8_t state = 0;
    static uint8_t payload[sizeof(GroundToBoat)];
    static size_t payloadIndex = 0;
    static uint8_t checksum = 0;

    while (Serial.available()) {
        const uint8_t value = (uint8_t)Serial.read();
        if (state == 0) {
            if (value == COMMAND_HEADER[0]) state = 1;
        } else if (state == 1) {
            state = value == COMMAND_HEADER[1] ? 2 : (value == COMMAND_HEADER[0] ? 1 : 0);
            payloadIndex = 0;
            checksum = 0;
        } else if (state == 2) {
            payload[payloadIndex++] = value;
            checksum += value;
            if (payloadIndex == sizeof(payload)) state = 3;
        } else {
            if (value == checksum) {
                memcpy(&sendData, payload, sizeof(sendData));
                lastCommandTime = millis();
                hasPendingCommand = true;
            }
            state = 0;
        }
    }
}

void stopStaleHostCommand() {
    if (millis() - lastCommandTime <= HOST_COMMAND_TIMEOUT_MS) return;
    sendData.mission_state = 0;
    sendData.release_flag = 0;
    sendData.manual_throttle = 0;
    sendData.manual_steer = 0;
}

// ==================== ESP-NOW 回调 ====================
void handleStatusFrame(const uint8_t *sourceMac, const uint8_t *incomingData, int len) {
    if (memcmp(sourceMac, dfr1063MAC, 6) != 0 || len != sizeof(BoatToGround)) return;
    portENTER_CRITICAL(&statusMux);
    memcpy(&pendingStatus, incomingData, sizeof(pendingStatus));
    pendingStatusReady = true;
    portEXIT_CRITICAL(&statusMux);
}

#if ESP_IDF_VERSION_MAJOR >= 5
void OnDataRecv(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len) {
    if (info != nullptr) handleStatusFrame(info->src_addr, incomingData, len);
}
#else
void OnDataRecv(const uint8_t *sourceMac, const uint8_t *incomingData, int len) {
    handleStatusFrame(sourceMac, incomingData, len);
}
#endif

bool configureEspNowRadio() {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false, true);
    delay(20);
    const esp_err_t channelResult = esp_wifi_set_channel(BOAT_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (channelResult != ESP_OK) {
        Serial.printf("设置 Wi-Fi 信道失败: %s\n", esp_err_to_name(channelResult));
        return false;
    }
    uint8_t primary = 0;
    wifi_second_chan_t secondary = WIFI_SECOND_CHAN_NONE;
    esp_wifi_get_channel(&primary, &secondary);
    // 本行打印的是桥接板自身 MAC —— 它必须与 main.ino 的 BOAT_BRIDGE_MAC 一致
    Serial.printf("桥接板 MAC: %s, 信道: %u\n", WiFi.macAddress().c_str(), primary);
    return primary == BOAT_WIFI_CHANNEL && secondary == WIFI_SECOND_CHAN_NONE;
}

void flushPendingStatus() {
    portENTER_CRITICAL(&statusMux);
    if (!pendingStatusReady) {
        portEXIT_CRITICAL(&statusMux);
        return;
    }
    memcpy(&recvData, &pendingStatus, sizeof(recvData));
    pendingStatusReady = false;
    portEXIT_CRITICAL(&statusMux);

    Serial.write(STATUS_HEADER, sizeof(STATUS_HEADER));
    Serial.write((uint8_t *)&recvData, sizeof(recvData));
    uint8_t checksum = 0;
    const uint8_t *bytes = (const uint8_t *)&recvData;
    for (size_t i = 0; i < sizeof(recvData); i++) checksum += bytes[i];
    Serial.write(checksum);
}

// ==================== 初始化 ====================
void setup() {
    Serial.begin(SERIAL_BAUD);
    delay(1000);
    Serial.println("ESP32-S3 桥接板启动...");

    memcpy(dfr1063MAC, BOAT_CONTROLLER_MAC, 6);

    if (!configureEspNowRadio()) {
        Serial.println("无线信道初始化失败，停止发送");
        return;
    }

    if (esp_now_init() != ESP_OK) {
        Serial.println("ESP-NOW 初始化失败！");
        return;
    }
    esp_now_register_recv_cb(OnDataRecv);

    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, dfr1063MAC, 6);
    peerInfo.channel = BOAT_WIFI_CHANNEL;
    peerInfo.ifidx = WIFI_IF_STA;
    peerInfo.encrypt = false;
    Serial.printf("目标船载 MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
        dfr1063MAC[0], dfr1063MAC[1], dfr1063MAC[2], dfr1063MAC[3], dfr1063MAC[4], dfr1063MAC[5]);
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
        Serial.println("❌ 添加 DFR1063 失败，请检查MAC！");
        return;
    }
    Serial.println("ESP-NOW 初始化成功，等待电脑指令...");
    lastPollTime = millis();
    lastCommandTime = millis();
}

// ==================== 主循环 ====================
void loop() {
    readSerialCommands();
    stopStaleHostCommand();
    flushPendingStatus();

    // 有指令立即发，无指令则定时轮询
    bool shouldSend = false;
    if (hasPendingCommand) {
        shouldSend = true;
        hasPendingCommand = false;
    } else if (millis() - lastPollTime >= POLL_INTERVAL_MS) {
        shouldSend = true;
    }

    if (shouldSend) {
        lastPollTime = millis();
        const esp_err_t sendResult = esp_now_send(dfr1063MAC, (uint8_t *)&sendData, sizeof(sendData));
        if (sendResult != ESP_OK && millis() - lastSendErrorPrint >= 1000) {
            lastSendErrorPrint = millis();
            Serial.printf("发送船载命令失败: %s (%d)\n", esp_err_to_name(sendResult), sendResult);
        }
    }

    delay(1);
}
