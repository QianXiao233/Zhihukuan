# 桥接板工程环境准备（ESP-IDF v6.1，EIM 安装布局）
#
# 用法：
#     cd E:\Users\CKJ\Desktop\Zhihukuan\Hardware\Firmware\boat\bridge-idf
#     . .\idf-env.ps1
#     idf.py build
#     idf.py -p COM12 flash monitor
#
# 说明：EIM 装的 IDF 需要手动设 8 个环境变量，少一个（尤其 ESP_IDF_VERSION）
# idf.py 会直接抛 TypeError 崩溃。

if (-not $env:IDF_PATH) { $env:IDF_PATH = 'F:\esp\v6.1\esp-idf' }
if (-not (Test-Path -LiteralPath "$env:IDF_PATH\tools\idf.py")) {
    throw "ESP-IDF 未找到: $env:IDF_PATH（请先设置 `$env:IDF_PATH）"
}

$env:IDF_TOOLS_PATH      = 'C:\Espressif\tools'
$env:IDF_PYTHON_ENV_PATH = 'C:\Espressif\tools\python\v6.1\venv'
$env:IDF_CCACHE_ENABLE   = '1'
$env:PYTHONUTF8          = '1'   # 否则 idf.py 会报 Unicode 环境警告

# 推导 IDF 版本（EIM 的 profile 会做这件事，手写环境时容易漏）
$versionCmake = "$env:IDF_PATH\tools\cmake\version.cmake"
if (Test-Path -LiteralPath $versionCmake) {
    $vc    = Get-Content -LiteralPath $versionCmake
    $major = ($vc | Select-String '^set\(IDF_VERSION_MAJOR (\d+)').Matches[0].Groups[1].Value
    $minor = ($vc | Select-String '^set\(IDF_VERSION_MINOR (\d+)').Matches[0].Groups[1].Value
    $patch = ($vc | Select-String '^set\(IDF_VERSION_PATCH (\d+)').Matches[0].Groups[1].Value
    $env:ESP_IDF_VERSION = "$major.$minor"
    $env:IDF_VERSION     = "$major.$minor.$patch"
}

$env:ESP_ROM_ELF_DIR     = 'C:\Espressif\tools\esp-rom-elfs\20241011'
$env:OPENOCD_SCRIPTS     = 'C:\Espressif\tools\openocd-esp32\v0.12.0-esp32-20260703\openocd-esp32\share\openocd\scripts'
$env:ESP_CLANG_LIBS_PATH = 'C:\Espressif\tools\esp-clang-libs\esp-21.1.3_20260408\esp-clang\lib'

$toolDirs = @(
    'C:\Espressif\tools\ccache\4.12.1\ccache-4.12.1-windows-x86_64'
    'C:\Espressif\tools\cmake\4.0.3\bin'
    'C:\Espressif\tools\dfu-util\0.11\dfu-util-0.11-win64'
    'C:\Espressif\tools\esp-clang\esp-21.1.3_20260408\esp-clang\bin'
    'C:\Espressif\tools\esp-clangd\esp-21.1.3_20260408\esp-clangd\bin'
    'C:\Espressif\tools\esp-rom-elfs\20241011'
    'C:\Espressif\tools\esp32ulp-elf\2.38_20240113\esp32ulp-elf\bin'
    'C:\Espressif\tools\idf-exe\1.0.3'
    'C:\Espressif\tools\ninja\1.12.1'
    'C:\Espressif\tools\openocd-esp32\v0.12.0-esp32-20260703\openocd-esp32\bin'
    'C:\Espressif\tools\riscv32-esp-elf\esp-15.2.0_20251204\riscv32-esp-elf\bin'
    'C:\Espressif\tools\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\bin'
    'C:\Espressif\tools\xtensa-esp-elf\esp-15.2.0_20251204\xtensa-esp-elf\xtensa-esp-elf\bin'
    'C:\Espressif\tools\python\v6.1\venv\Scripts'
) | Where-Object { Test-Path -LiteralPath $_ }

$env:PATH = ($toolDirs -join ';') + ';' + $env:PATH

function global:Invoke-idfpy {
    & "$env:IDF_PYTHON_ENV_PATH\Scripts\python.exe" "$env:IDF_PATH\tools\idf.py" @args
}
Set-Alias -Name idf.py -Value Invoke-idfpy -Force

Write-Host "ESP-IDF $env:IDF_VERSION 环境就绪（boat-bridge）" -ForegroundColor Green
