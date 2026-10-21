/**
 * DFR1063 主控 - 自主航行 + 手动遥控 + 应急巡航
 * 逻辑：桥接板在则正常，桥接板断则3秒后应急
 */

#include <esp_now.h>
#include <WiFi.h>
#include <esp_wifi.h>
#include <esp_idf_version.h>
#include <Wire.h>
#include "DFRobot_HuskylensV2.h"

#include "../boat_config.h"   // 桥接板 MAC / 信道统一由此文件提供

// ==================== 系统开关 ====================
bool ENABLE_DEBUG = true;
bool ENABLE_MOTOR_OUTPUT = true;

// ==================== 通信与测距参数 ====================
const unsigned long COMM_TIMEOUT_MS = 3000;
bool emergencyMode = false;
bool radioReady = false;
unsigned long lastRecvTime = 0;

const float FOCAL_LENGTH = 500.0;
const float OBSTACLE_REAL_WIDTH = 0.10;
const float COARSE_ARRIVAL_RADIUS_M = 0.40;
const float VISUAL_STOP_DISTANCE_M = 0.20;

// 桥接板的 ESP-NOW MAC（Wi-Fi STA 接口），定义见 arduino-reference/boat_config.h
// 已更换为 Waveshare ESP32-S3-LCD-1.47，实测 MAC = A0:F2:62:E3:94:DC
uint8_t bridgeMAC[6];

// ==================== 引脚定义 ====================
#define M1_PWM  0
#define M1_DIR  1
#define M2_PWM  2
#define M2_DIR  10
#define SERVO_PIN 6
const bool M1_DIRECTION_INVERTED = true;

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

GroundToBoat cmd;
BoatToGround status;
GroundToBoat pendingCmd;
volatile bool pendingCmdReady = false;
portMUX_TYPE commandMux = portMUX_INITIALIZER_UNLOCKED;

static_assert(sizeof(GroundToBoat) == 26, "GroundToBoat layout must be 26 bytes");
static_assert(sizeof(BoatToGround) == 32, "BoatToGround layout must be 32 bytes");

// ==================== 对象与PID ====================
HuskylensV2 huskylens;
float Kp = 2.0, Ki = 0.0, Kd = 0.5;
float integral = 0, lastError = 0;

// ==================== 全局变量 ====================
bool target_detected = false;
bool huskylensReady = false;
int local_target_x = 0;
int local_target_y = 0;
int target_width_px = 0;
int currentLeftSpeed = 0;
int currentRightSpeed = 0;
bool visualApproachActive = false;
bool approachTargetInitialized = false;
float approachTargetX = 0;
float approachTargetY = 0;

unsigned long lastHuskyRead = 0;
unsigned long lastDebugPrint = 0;
unsigned long lastSendErrorPrint = 0;
const unsigned long HUSKY_INTERVAL = 100;
const unsigned long DEBUG_INTERVAL = 500;

// ==================== ESP-NOW 接收回调 ====================
void handleCommandFrame(const uint8_t *sourceMac, const uint8_t *incomingData, int len) {
    if (memcmp(sourceMac, bridgeMAC, 6) != 0 || len != sizeof(cmd)) return;
    portENTER_CRITICAL(&commandMux);
    memcpy(&pendingCmd, incomingData, sizeof(pendingCmd));
    pendingCmdReady = true;
    portEXIT_CRITICAL(&commandMux);
}

#if ESP_IDF_VERSION_MAJOR >= 5
void OnDataRecv(const esp_now_recv_info_t *info, const uint8_t *incomingData, int len) {
    if (info != nullptr) handleCommandFrame(info->src_addr, incomingData, len);
}
#else
void OnDataRecv(const uint8_t *sourceMac, const uint8_t *incomingData, int len) {
    handleCommandFrame(sourceMac, incomingData, len);
}
#endif

void applyPendingCommand() {
    bool ready = false;
    portENTER_CRITICAL(&commandMux);
    if (pendingCmdReady) {
        memcpy(&cmd, &pendingCmd, sizeof(cmd));
        pendingCmdReady = false;
        ready = true;
    }
    portEXIT_CRITICAL(&commandMux);
    if (!ready) return;
    lastRecvTime = millis();

    if (emergencyMode) {
        emergencyMode = false;
        integral = 0;
        lastError = 0;
        visualApproachActive = false;
        approachTargetInitialized = false;
        if (ENABLE_DEBUG) Serial.println("通信恢复，退出应急模式！");
    }
}

bool configureEspNowRadio() {
    WiFi.mode(WIFI_STA);
    WiFi.disconnect(false, true);
    delay(20);
    const esp_err_t channelResult = esp_wifi_set_channel(BOAT_WIFI_CHANNEL, WIFI_SECOND_CHAN_NONE);
    if (channelResult != ESP_OK) {
        if (ENABLE_DEBUG) Serial.printf("设置 Wi-Fi 信道失败: %s\n", esp_err_to_name(channelResult));
        return false;
    }
    uint8_t primary = 0;
    wifi_second_chan_t secondary = WIFI_SECOND_CHAN_NONE;
    esp_wifi_get_channel(&primary, &secondary);
    // 本行打印的是船载主控自身 MAC —— 它必须与 controller.ino 的 BOAT_CONTROLLER_MAC 一致
    if (ENABLE_DEBUG) Serial.printf("船载 MAC: %s, 信道: %u\n", WiFi.macAddress().c_str(), primary);
    return primary == BOAT_WIFI_CHANNEL && secondary == WIFI_SECOND_CHAN_NONE;
}

// ==================== 初始化 ====================
void setup() {
    if (ENABLE_DEBUG) {
        Serial.begin(115200);
        delay(1000);
        Serial.println("DFR1063 启动...");
        if (!ENABLE_MOTOR_OUTPUT) Serial.println("⚠️ 电机输出已禁用（陆地调试模式）");
    }

    memcpy(bridgeMAC, BOAT_BRIDGE_MAC, 6);

    pinMode(M1_PWM, OUTPUT); pinMode(M1_DIR, OUTPUT);
    pinMode(M2_PWM, OUTPUT); pinMode(M2_DIR, OUTPUT);
    stopAll();

    if (!configureEspNowRadio()) {
        if (ENABLE_DEBUG) Serial.println("无线信道初始化失败，保持电机停止");
        return;
    }
    if (esp_now_init() != ESP_OK) {
        if (ENABLE_DEBUG) Serial.println("ESP-NOW 初始化失败！");
        return;
    }
    esp_now_register_recv_cb(OnDataRecv);

    esp_now_peer_info_t peerInfo = {};
    memcpy(peerInfo.peer_addr, bridgeMAC, 6);
    peerInfo.channel = BOAT_WIFI_CHANNEL;
    peerInfo.ifidx = WIFI_IF_STA;
    peerInfo.encrypt = false;
    if (ENABLE_DEBUG) Serial.printf("目标桥接板 MAC: %02X:%02X:%02X:%02X:%02X:%02X\n",
        bridgeMAC[0], bridgeMAC[1], bridgeMAC[2], bridgeMAC[3], bridgeMAC[4], bridgeMAC[5]);
    if (esp_now_add_peer(&peerInfo) != ESP_OK) {
        if (ENABLE_DEBUG) Serial.println("❌ 添加桥接板失败，请检查MAC！");
        return;
    }
    radioReady = true;
    Wire.begin(8, 9);
    const unsigned long huskyDeadline = millis() + 3000;
    while (!huskylensReady && millis() < huskyDeadline) {
        huskylensReady = huskylens.begin(Wire);
        if (!huskylensReady) delay(100);
    }
    if (huskylensReady) {
        huskylens.switchAlgorithm(ALGORITHM_OBJECT_TRACKING);
        delay(500);
        if (ENABLE_DEBUG) Serial.println("HUSKYLENS 2 初始化成功！");
    } else if (ENABLE_DEBUG) {
        Serial.println("HUSKYLENS 2 未连接，继续使用 ESP-NOW 手动控制");
    }
    lastRecvTime = millis();
    if (ENABLE_DEBUG) Serial.println("ESP-NOW 初始化成功！");
}

// ==================== 主循环 ====================
void loop() {
    if (!radioReady) {
        stopAll();
        delay(50);
        return;
    }

    applyPendingCommand();
    // 1. 按10Hz读取二哈
    if (millis() - lastHuskyRead >= HUSKY_INTERVAL) {
        lastHuskyRead = millis();
        target_detected = false;
        target_width_px = 0;
        if (huskylensReady && huskylens.getResult(ALGORITHM_OBJECT_TRACKING)) {
            if (huskylens.available(ALGORITHM_OBJECT_TRACKING)) {
                Result *result = huskylens.popCachedResult(ALGORITHM_OBJECT_TRACKING);
                if (result != NULL) {
                    local_target_x = result->xCenter;
                    local_target_y = result->yCenter;
                    target_width_px = result->width;
                    target_detected = target_width_px > 0;
                }
            }
        }
    }

    // 2. 计算二哈估算距离
    float estimated_dist = 999.0;
    if (target_detected && target_width_px > 0) {
        estimated_dist = (OBSTACLE_REAL_WIDTH * FOCAL_LENGTH) / target_width_px;
        if (estimated_dist > 5.0) estimated_dist = 5.0;
    }

    // 3. 通信状态判断（桥接板是否还在）
    bool commTimeout = (millis() - lastRecvTime > COMM_TIMEOUT_MS);

    if (commTimeout) {
        if (!emergencyMode) {
            emergencyMode = true;
            integral = 0; lastError = 0;
            if (ENABLE_DEBUG) Serial.println("=== 通信中断！进入应急模式 ===");
        }
        visualApproachActive = false;
        approachTargetInitialized = false;
        emergencyCruise(estimated_dist);
    } else {
        if (cmd.mission_state != 1) {
            visualApproachActive = false;
            approachTargetInitialized = false;
        }
        switch(cmd.mission_state) {
            case 1: navigateToTarget(estimated_dist); break;
            case 2:
                stopAll();
                if (cmd.release_flag == 1) { releasePayload(); cmd.release_flag = 0; }
                break;
            case 4: manualControl(); break;
            default: stopAll(); break;
        }
    }

    // 4. 上报状态（桥接板在时才发）
    if (!commTimeout) {
        status.boat_heading = -1.0; // No compass sensor is installed yet.
        status.left_motor_speed = currentLeftSpeed;
        status.right_motor_speed = currentRightSpeed;
        status.target_detected = target_detected ? 1 : 0;
        status.local_target_x = local_target_x;
        status.local_target_y = local_target_y;
        status.estimated_dist_m = estimated_dist;
        status.emergency_mode = emergencyMode ? 1 : 0;
        const esp_err_t sendResult = esp_now_send(bridgeMAC, (uint8_t *)&status, sizeof(status));
        if (sendResult != ESP_OK && ENABLE_DEBUG && millis() - lastSendErrorPrint >= 1000) {
            lastSendErrorPrint = millis();
            Serial.printf("发送状态失败: %s (%d)\n", esp_err_to_name(sendResult), sendResult);
        }
    }

    // 5. 节流调试输出
    if (ENABLE_DEBUG && (millis() - lastDebugPrint >= DEBUG_INTERVAL)) {
        lastDebugPrint = millis();
        Serial.print("[状态] ");
        if (commTimeout) Serial.print("应急");
        else if (cmd.mission_state == 4) Serial.print("手动");
        else if (cmd.mission_state == 1) Serial.print(visualApproachActive ? "自主-二哈靠近" : "自主-坐标导航");
        else Serial.print("待命");
        Serial.print(" | 二哈:");
        Serial.print(target_detected ? "有目标" : "无目标");
        if (target_detected) {
            Serial.print(" X="); Serial.print(local_target_x);
            Serial.print(" 距离="); Serial.print(estimated_dist);
        }
        Serial.print(" | 电机 L="); Serial.print(currentLeftSpeed);
        Serial.print(" R="); Serial.println(currentRightSpeed);
    }

    delay(50);
}

// ==================== 手动遥控模式 ====================
void manualControl() {
    int throttle = cmd.manual_throttle;
    int steer = cmd.manual_steer;

    int leftPWM = throttle + steer;
    int rightPWM = throttle - steer;

    leftPWM = constrain(leftPWM, -200, 200);
    rightPWM = constrain(rightPWM, -200, 200);

    bool leftForward = (leftPWM >= 0);
    bool rightForward = (rightPWM >= 0);

    currentLeftSpeed = leftPWM;
    currentRightSpeed = rightPWM;

    setMotor(M1_PWM, M1_DIR, abs(leftPWM), leftForward);
    setMotor(M2_PWM, M2_DIR, abs(rightPWM), rightForward);
}

// ==================== 自主航行控制 ====================
void navigateToTarget(float visionDistance) {
    if (!approachTargetInitialized || fabsf(cmd.target_x - approachTargetX) > 0.30f ||
        fabsf(cmd.target_y - approachTargetY) > 0.30f) {
        approachTargetX = cmd.target_x;
        approachTargetY = cmd.target_y;
        approachTargetInitialized = true;
        visualApproachActive = false;
    }

    const float dist = sqrtf(powf(cmd.target_x - cmd.boat_x, 2) + powf(cmd.target_y - cmd.boat_y, 2));
    if (!visualApproachActive && dist <= COARSE_ARRIVAL_RADIUS_M) {
        visualApproachActive = true;
        integral = 0;
        lastError = 0;
        if (ENABLE_DEBUG) Serial.println("坐标到达末端区域，切换二哈精细靠近");
    }

    if (visualApproachActive) {
        if (!target_detected) {
            stopAll();
            return;
        }
        if (visionDistance <= VISUAL_STOP_DISTANCE_M) {
            stopAll();
            if (ENABLE_DEBUG) Serial.println("二哈测距已到停靠距离，停车");
            return;
        }

        const float localError = (local_target_x - 320) / 320.0f;
        const int correction = (int)(localError * 90.0f);
        currentLeftSpeed = constrain(75 + correction, 0, 140);
        currentRightSpeed = constrain(75 - correction, 0, 140);
        setMotor(M1_PWM, M1_DIR, currentLeftSpeed, true);
        setMotor(M2_PWM, M2_DIR, currentRightSpeed, true);
        return;
    }

    float desired_heading = atan2(cmd.target_x - cmd.boat_x, cmd.target_y - cmd.boat_y) * 180.0 / PI;
    if (desired_heading < 0) desired_heading += 360.0;

    float error = desired_heading - cmd.boat_heading;
    if (error > 180)  error -= 360;
    if (error < -180) error += 360;

    integral += error;
    integral = constrain(integral, -500, 500);
    float derivative = error - lastError;
    float correction = Kp * error + Ki * integral + Kd * derivative;
    lastError = error;

    int baseSpeed = 100;
    currentLeftSpeed  = constrain(baseSpeed + (int)correction, 0, 180);
    currentRightSpeed = constrain(baseSpeed - (int)correction, 0, 180);
    setMotor(M1_PWM, M1_DIR, currentLeftSpeed, true);
    setMotor(M2_PWM, M2_DIR, currentRightSpeed, true);

}

// ==================== 应急自动巡航 ====================
void emergencyCruise(float visionDistance) {
    if (target_detected) {
        if (visionDistance <= VISUAL_STOP_DISTANCE_M) {
            stopAll();
            if (ENABLE_DEBUG) Serial.println("应急搜到目标并到达停靠距离，停车");
            return;
        }
        float local_error = (local_target_x - 320) / 320.0;
        int baseSpeed = 80;
        int correction = (int)(local_error * 80.0);
        currentLeftSpeed  = constrain(baseSpeed + correction, 0, 150);
        currentRightSpeed = constrain(baseSpeed - correction, 0, 150);
        setMotor(M1_PWM, M1_DIR, currentLeftSpeed, true);
        setMotor(M2_PWM, M2_DIR, currentRightSpeed, true);
    } else {
        currentLeftSpeed = 70;
        currentRightSpeed = -70;
        setMotor(M1_PWM, M1_DIR, currentLeftSpeed, true);
        setMotor(M2_PWM, M2_DIR, currentRightSpeed, false);
    }
}

// ==================== 电机与释放函数 ====================
void stopAll() {
    analogWrite(M1_PWM, 0);
    analogWrite(M2_PWM, 0);
    currentLeftSpeed = 0;
    currentRightSpeed = 0;
}

void setMotor(int pwmPin, int dirPin, int speed, bool forward) {
    if (!ENABLE_MOTOR_OUTPUT) {
        analogWrite(pwmPin, 0);
        return;
    }
    speed = constrain(speed, 0, 255);
    const bool electricalForward = (dirPin == M1_DIR && M1_DIRECTION_INVERTED) ? !forward : forward;
    digitalWrite(dirPin, electricalForward ? LOW : HIGH);
    analogWrite(pwmPin, speed);
}

void releasePayload() {
    if (ENABLE_DEBUG) Serial.println("触发释放机构！");
    // servo.write(90); delay(500); servo.write(0);
}
