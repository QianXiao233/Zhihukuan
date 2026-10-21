cmake_minimum_required(VERSION 3.16)

# 桥接板固件（Waveshare ESP32-S3-LCD-1.47）
# 平台: ESP-IDF v6.1
# 显示驱动复用自 ESP32-S3-LCD-1.47-Demo 工程（已实测 50 MHz 像素时钟 / 横屏）
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(boat-bridge)
