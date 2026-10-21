/**
 * MAC 诊断固件 —— 烧到要做桥接板的 ESP32-S3-LCD-1.47 上，
 * 从串口读出 Wi-Fi STA MAC，填入 controller.ino 的 dfr1063MAC
 * 和 main.ino 的 bridgeMAC。
 *
 * 说明：ESP-NOW 使用 Wi-Fi STA 接口的 MAC，即 WiFi.macAddress() 的返回值。
 * 该值通常等于 eFuse 基址 MAC，但部分 ESP32-S3 模组（4 个通用 MAC 的批次）
 * 会有偏移，所以必须实测，不能推断。
 *
 * 注意：ESP32-S3 用原生 USB-Serial-JTAG，DTR/RTS 组合容易把芯片拉进
 * 下载模式。所以这里在 loop() 里周期性重复打印，打开串口即可收到，
 * 不需要任何复位操作。
 */
#include <WiFi.h>
#include <esp_mac.h>

static uint8_t sta[6] = {0};

static void printReport() {
    Serial.println();
    Serial.println("========== MAC REPORT ==========");
    Serial.printf("CHIP_MODEL             : %s\n", ESP.getChipModel());
    Serial.printf("CHIP_CORES             : %d\n", ESP.getChipCores());
    Serial.printf("EFUSE_MAC (getEfuseMac): %04X%08X\n",
                  (uint16_t)(ESP.getEfuseMac() >> 32), (uint32_t)ESP.getEfuseMac());

    Serial.printf("WIFI STA  (ESP-NOW)    : %02X:%02X:%02X:%02X:%02X:%02X\n",
                  sta[0], sta[1], sta[2], sta[3], sta[4], sta[5]);

    uint8_t ap[6] = {0};
    uint8_t bt[6] = {0};
    esp_read_mac(ap, ESP_MAC_WIFI_SOFTAP);
    esp_read_mac(bt, ESP_MAC_BT);
    Serial.printf("ESP_MAC_WIFI_SOFTAP    : %02X:%02X:%02X:%02X:%02X:%02X\n",
                  ap[0], ap[1], ap[2], ap[3], ap[4], ap[5]);
    Serial.printf("ESP_MAC_BT             : %02X:%02X:%02X:%02X:%02X:%02X\n",
                  bt[0], bt[1], bt[2], bt[3], bt[4], bt[5]);

    Serial.println();
    Serial.println("--- COPY THIS LINE (C array for ESP-NOW) ---");
    Serial.printf("uint8_t bridgeMAC[] = {0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X, 0x%02X};\n",
                  sta[0], sta[1], sta[2], sta[3], sta[4], sta[5]);
    Serial.println("=================================");
}

void setup() {
    Serial.begin(115200);
    delay(1500);              // 等 USB CDC 枚举完成
    WiFi.mode(WIFI_STA);
    delay(200);
    WiFi.macAddress(sta);     // ← ESP-NOW 用的就是它
    printReport();
}

void loop() {
    delay(3000);
    printReport();            // 周期重复，便于随时抓取
}
