#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无人艇硬件上线自检：识别串口上的船载主控 / 桥接板，并检查二哈 U 盘。

背景：船载主控（ESP32-C3）和桥接板（ESP32-S3）的 USB VID/PID 完全相同，
光看设备管理器分不出来；烧错固件会把桥接板刷成主控。本脚本通过**读启动日志**
按 TAG 区分（BOAT_* = 主控，BRIDGE_* = 桥接板），再给出下一步命令。

用法：
    python hardware_check.py                 # 只列当前在线串口
    python hardware_check.py --read          # 被动监听 3 秒，看谁在输出（不重启板子）
    python hardware_check.py --read --reset  # 静默时用 DTR/RTS 复位再抓启动日志（会重启板子）
    python hardware_check.py --install runs\\package\\xxx.zip   # 发现二哈 U 盘时把安装包拷进去

依赖：pyserial（pip install pyserial）
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

CONTROLLER_PATTERNS = (
    "BOAT_MAIN", "BOAT_LINK", "BOAT_HUSKY", "BOAT_MOTORS", "BOAT_NAV", "BOAT_SERVO",
    "BOAT_PROTO", "HUSKYLENS 算法 ID", "HUSKYLENS 2 初始化", "通信中断", "应急模式",
)
BRIDGE_PATTERNS = ("BRIDGE_MAIN", "BRIDGE_ESPNOW", "BRIDGE_PROTO", "桥接板启动", "ESP-NOW 初始化完成")


def serial_available():
    try:
        import serial  # noqa: F401
        from serial.tools import list_ports  # noqa: F401

        return True
    except ImportError:
        return False


def list_serial_ports() -> list:
    from serial.tools import list_ports

    ports = []
    for info in list_ports.comports():
        vid = f"{info.vid:04X}" if info.vid else "-"
        pid = f"{info.pid:04X}" if info.pid else "-"
        ports.append({
            "device": info.device,
            "description": info.description or "",
            "vid": vid,
            "pid": pid,
            "is_espressif": vid == "303A",
        })
    return ports


def read_port(device: str, seconds: float, reset: bool) -> str:
    import serial

    try:
        ser = serial.Serial(device, 115200, timeout=0.3)
    except Exception as exc:
        return f"<打开失败：{exc}>"
    try:
        if reset:
            # esptool 的经典复位时序：EN 拉低再拉高
            ser.setDTR(False)
            ser.setRTS(True)
            time.sleep(0.1)
            ser.setDTR(True)
            ser.setRTS(False)
            time.sleep(0.1)
        ser.reset_input_buffer()
        deadline = time.time() + seconds
        data = b""
        while time.time() < deadline:
            chunk = ser.read(256)
            if chunk:
                data += chunk
        return data.decode("utf-8", "replace")
    finally:
        ser.close()


def classify(text: str) -> tuple[str, list[str]]:
    hit_controller = [p for p in CONTROLLER_PATTERNS if p in text]
    hit_bridge = [p for p in BRIDGE_PATTERNS if p in text]
    if hit_controller and not hit_bridge:
        return "船载主控（controller）", hit_controller
    if hit_bridge and not hit_controller:
        return "桥接板（bridge）", hit_bridge
    if hit_controller and hit_bridge:
        return "无法确定（两条链路日志都有）", hit_controller + hit_bridge
    return "未知（没抓到特征日志）", []


def find_huskylens_drives() -> list[Path]:
    """找二哈 U 盘：卷标 HUSKYLENS，或根目录下存在 storage/installation_package。"""
    drives = []
    if sys.platform != "win32":
        for root in (Path("/media"), Path("/mnt"), Path("/Volumes")):
            if root.is_dir():
                for child in root.iterdir():
                    if child.is_dir() and (child / "storage").is_dir():
                        drives.append(child)
        return drives
    import string

    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        if not root.exists():
            continue
        if (root / "storage" / "installation_package").is_dir():
            drives.append(root)
    return drives


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="无人艇硬件上线自检")
    ap.add_argument("--read", action="store_true", help="读串口日志（被动 3 秒）")
    ap.add_argument("--reset", action="store_true", help="静默时复位再读（会重启板子）")
    ap.add_argument("--seconds", type=float, default=3.0, help="每个串口监听秒数（默认 3）")
    ap.add_argument("--install", default=None, help="把指定 zip 拷进二哈 U 盘的 storage/installation_package")
    args = ap.parse_args(argv)

    if not serial_available() and (args.read or args.install is None):
        print("[hw] 缺少 pyserial，先安装：pip install pyserial", file=sys.stderr)
        return 2

    print("=" * 70)
    print("无人艇硬件上线自检")
    print("=" * 70)

    # ---- 1. 二哈 U 盘 ----
    drives = find_huskylens_drives()
    if drives:
        for drive in drives:
            target = drive / "storage" / "installation_package"
            print(f"[hw] 发现二哈 U 盘：{drive}（安装包目录 {target}）")
            if args.install:
                package = Path(args.install).resolve()
                if not package.is_file():
                    print(f"[hw] 错误：安装包不存在 {package}", file=sys.stderr)
                    return 2
                shutil.copy2(package, target / package.name)
                print(f"[hw] 已拷贝 {package.name} 到 U 盘；下一步在设备上「模型安装 → 本地安装」")
        if args.install:
            return 0
    else:
        print("[hw] 没有发现二哈 U 盘（USB 连上二哈后应出现名为 HUSKYLENS 2 的盘）")

    # ---- 2. 串口 ----
    if not serial_available():
        print("[hw] 缺少 pyserial，跳过串口检查", file=sys.stderr)
        return 2
    ports = list_serial_ports()
    if not ports:
        print("[hw] 当前没有在线串口设备。把船载主控/桥接板 USB 插上后重跑本脚本。")
        return 1
    print(f"\n[hw] 在线串口 {len(ports)} 个：")
    for info in ports:
        tag = "  <-- ESP32" if info["is_espressif"] else ""
        print(f"  {info['device']:<8} {info['vid']}:{info['pid']}  {info['description']}{tag}")

    if not args.read:
        print("\n[hw] 加 --read 可读日志识别哪块是船载主控/桥接板（不会重启板子）")
        return 0

    # ---- 3. 读日志识别 ----
    print()
    conclusions = []
    for info in ports:
        device = info["device"]
        text = read_port(device, args.seconds, reset=args.reset)
        if args.reset and len(text.strip()) < 5:
            # 复位后仍没输出，再给一次机会（有些板子复位慢）
            text = read_port(device, args.seconds, reset=False)
        role, evidence = classify(text)
        print(f"[hw] {device} -> {role}")
        if evidence:
            print(f"     证据：{', '.join(evidence[:5])}")
        tail = [line.strip() for line in text.splitlines() if line.strip()][-3:]
        for line in tail:
            print(f"     日志 | {line[:140]}")
        conclusions.append((device, role, text))
        if "HUSKYLENS 算法 ID" in text:
            for line in text.splitlines():
                if "HUSKYLENS 算法 ID" in line:
                    print(f"     >>> 当前固件使用的算法 ID：{line.strip()[:120]}")
                    break

    # ---- 4. 下一步 ----
    print("\n" + "=" * 70)
    controller = [device for device, role, _ in conclusions if role.startswith("船载主控")]
    bridge = [device for device, role, _ in conclusions if role.startswith("桥接板")]
    if controller:
        print(f"船载主控：{', '.join(controller)}")
        print("  烧录命令（先改 HUSKY_ALGORITHM_ID 再编译）：")
        for device in controller:
            print(f"    cd Hardware\\Firmware\\boat\\controller-idf; . .\\idf-env.ps1; idf.py -p {device} flash monitor")
    if bridge:
        print(f"桥接板：{', '.join(bridge)}（烧的是 bridge-idf 固件，别和主控搞混）")
    if not controller and not bridge:
        print("没识别出板子：确认 USB 已插、驱动正常（设备管理器应有 COM 口），或加 --reset 重试。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
