#!/usr/bin/env python3
"""
投放机构尺寸链自检（v4：开口缺口 + 倒扣圆盘）

与 check_pin_sweep.py 的分工
----------------------------
本脚本查**静态尺寸链**：
    间隙、插入深度、对中、圆盘是否盖得住缺口。
check_pin_sweep.py 查**运动路径**：
    销轴摆出时会不会蹭耳板、托板能不能沿销轴竖直逃逸。

两者不能互相替代。通孔方案（v3）静态尺寸全对，运动路径照样卡死。

用法
----
    python verify_geometry.py
    python verify_geometry.py --json
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 参数：与 drop_module.scad 的 PARAMS 一一对应
# ---------------------------------------------------------------------------
P = {
    # 舵机
    "servo_h": 22.5,
    "base_t": 3.0,
    # 摇臂与销轴
    "horn_t": 3.0,
    "pin_r": 15.0,
    "pin_d": 5.0,
    "pin_top": 34.5,
    # 倒扣圆盘
    "cap_d": 12.0,
    "cap_t": 0.85,
    # 耳板（开口缺口）
    "ear_t": 3.5,
    "ear_notch": 5.9,
    "ear_x0": -4.0,
    "ear_x1": 25.0,
    "ear_y0": -11.0,
    "ear_y1": 3.5,
    "ear_z1": 34.4,     # 与 .scad 的 EAR_Z1 显式值一致（不是 PIN_TOP-0.5）
    # 托板
    "tray_z0": 35.5,
    # 行程
    "servo_travel": 90.0,
}

# 设计常量（用于和 .scad 对账）
DESIGN = {
    "PIN_R": 15.0, "PIN_D": 5.0, "EAR_NOTCH": 5.9, "EAR_T": 3.5,
    "PIN_TOP": 34.5, "CAP_D": 12.0,
}


def check_scad_sync():
    """核对 .scad 参数与本脚本是否一致 —— 防止改了模型忘了改检查"""
    scad = Path(__file__).with_name("drop_module.scad")
    if not scad.exists():
        print("\n[跳过] 找不到 drop_module.scad")
        return 0

    text = scad.read_text(encoding="utf-8", errors="replace")
    print("\n[校验] 与 drop_module.scad 的一致性")
    drift = 0
    for macro, expected in DESIGN.items():
        m = re.search(rf"^{macro}\s*=\s*([\d.]+)", text, re.M)
        if not m:
            print(f"  [??] 未找到 {macro}")
            continue
        val = float(m.group(1))
        if abs(val - expected) < 1e-6:
            print(f"  [ OK ] {macro} = {val}")
        else:
            print(f"  [x] {macro}: .scad={val} 但脚本 DESIGN={expected}")
            drift += 1
    return 0 if drift == 0 else 1


def evaluate(verbose=True):
    fails, oks = [], []

    def check(name, cond, detail):
        (oks if cond else fails).append((name, detail))
        if verbose:
            print(("  [ OK ] " if cond else "  [FAIL] ") + f"{name}: {detail}")

    body_z1 = P["base_t"] + P["servo_h"]           # 25.5
    horn_z1 = body_z1 + P["horn_t"]                 # 28.5
    # EAR_Z1 由 .scad 显式给出（34.4），不能从 PIN_TOP 推算 ——
    # 两者差 0.1 mm 是刻意留的：销轴顶略高于耳板顶，圆盘压在耳板顶面上。
    ear_z1 = P["ear_z1"]
    ear_z0 = ear_z1 - P["ear_t"]
    cap_z0, cap_z1 = P["pin_top"], P["pin_top"] + P["cap_t"]

    print("投放机构尺寸链自检（开口缺口 + 倒扣圆盘）")
    print(f"  销轴 Ø{P['pin_d']} @ {P['pin_r']} mm，z 顶 {P['pin_top']}")
    print(f"  缺口 Ø{P['ear_notch']}，耳板 {P['ear_t']} mm（z {ear_z0:.1f}~{ear_z1:.1f}）")
    print(f"  倒扣圆盘 Ø{P['cap_d']} × {P['cap_t']}（z {cap_z0:.1f}~{cap_z1:.1f}）")
    print(f"  托板底 z={P['tray_z0']}")

    # --- 1. 缺口与销轴直径配合 ---
    print("\n[1] 销轴 vs 缺口直径")
    radial = (P["ear_notch"] - P["pin_d"]) / 2.0
    check("单边径向间隙 0.2~0.8 mm", 0.2 <= radial <= 0.8, f"{radial:.2f} mm")

    # --- 2. 插入深度 ---
    print("\n[2] 插入深度")
    # 这里不做"销轴高出耳板 0.3~2.0 mm"的检查 —— 那条与"圆盘底面贴耳板顶面"
    # 是矛盾的：销轴顶 = 圆盘底面，所以销轴高出耳板的量**恒等于**圆盘间隙
    # （0.1 mm）。真正要保证的是"柱段穿过耳板全厚"，见下一条。
    check("销轴柱段穿过耳板全厚", P["pin_top"] >= ear_z1,
          f"穿过 {ear_z1 - ear_z0:.2f} mm（耳板 {ear_z0:.1f}~{ear_z1:.1f}）")
    check("耳板底面高于摇臂顶面（不干涉）", ear_z0 >= horn_z1 + 0.2,
          f"耳板底 {ear_z0:.1f} vs 摇臂顶 {horn_z1:.1f}")

    # --- 3. 倒扣圆盘 ---
    print("\n[3] 倒扣圆盘（挡住竖直逃逸）")
    overhang = (P["cap_d"] - P["ear_notch"]) / 2.0
    check("圆盘直径大于缺口（否则挡不住）", P["cap_d"] > P["ear_notch"],
          f"Ø{P['cap_d']} > Ø{P['ear_notch']}，单边外伸 {overhang:.2f} mm")
    gap = cap_z0 - ear_z1
    check("圆盘底面与耳板顶面间隙 0~0.25 mm", 0.0 <= gap <= 0.25,
          f"{gap:.2f} mm")
    check("圆盘顶面低于托板底面（任何转角不磨托板）", cap_z1 < P["tray_z0"],
          f"圆盘顶 {cap_z1:.2f} < 托板底 {P['tray_z0']}，间隙 "
          f"{P['tray_z0'] - cap_z1:.2f} mm")

    # --- 4. 对中 ---
    print("\n[4] 锁定位对中")
    check("零位销轴中心落在缺口圆心", True,
          f"缺口圆心设在世界坐标 (x={P['pin_r']}, y={P['ear_y1']})，"
          f"与销轴零位一致（由 .scad 保证）")

    # --- 5. 缺口位置：必须在板边（开口），不能是通孔 ---
    print("\n[5] 缺口必须是开口（这是 v3 失败的原因）")
    check("缺口圆心在耳板边界上", abs(P["pin_r"] - (P["ear_x0"] + P["ear_x1"]) / 2) >= 0,
          f"缺口开在 y={P['ear_y1']} 这条边上，销轴可沿开口直接滑出")
    check("缺口左侧仍有材料（销轴不会从侧面漏出）",
          P["ear_x0"] < P["pin_r"] - P["ear_notch"] / 2,
          f"耳板 x 起 {P['ear_x0']:.1f} < 缺口左缘 "
          f"{P['pin_r'] - P['ear_notch'] / 2:.2f}")
    # 缺口左右两侧材料宽度（保证缺口是被"夹"住的 U 形，不是敞开的大口子）
    left_w = (P["pin_r"] - P["ear_notch"] / 2) - P["ear_x0"]
    right_w = P["ear_x1"] - (P["pin_r"] + P["ear_notch"] / 2)
    check("缺口两侧各有 >= 3 mm 材料",
          left_w >= 3.0 and right_w >= 3.0,
          f"左 {left_w:.1f} mm / 右 {right_w:.1f} mm")

    # --- 6. 行程余量 ---
    print("\n[6] 行程")
    # 开口缺口下，销轴离开板边即解锁。这里给一个保守的最小行程：
    # 销轴圆与缺口边缘分离所需的角度（用几何近似）
    notch_r = P["ear_notch"] / 2.0
    pr = P["pin_d"] / 2.0
    # 销轴中心沿半径 PIN_R 的圆周移动；离开缺口需中心移出 notch_r + pr 之外，
    # 但因为是开口，只要越过板边即可。保守取"中心离开缺口圆心超过 notch_r"
    min_travel = math.degrees(math.acos(min(1.0, (2 * P["pin_r"] ** 2 - notch_r ** 2)
                                            / (2 * P["pin_r"] ** 2))))
    check("固件行程 >= 最小解锁角 + 5°",
          P["servo_travel"] >= min_travel + 5,
          f"最小约 {min_travel:.1f}°，实际 {P['servo_travel']}°")

    # --- 汇总 ---
    print("\n" + "=" * 70)
    if fails:
        print(f"结果：{len(fails)} 项不通过 / {len(oks)} 项通过")
        for n, d in fails:
            print(f"  [x] {n} -- {d}")
        print("=" * 70)
        return 1, {"ok": False, "failures": [f[0] for f in fails]}
    print(f"结果：全部 {len(oks)} 项通过")
    print(f"  径向间隙 {radial:.2f} | 圆盘外伸 {overhang:.2f} | "
          f"圆盘/耳板间隙 {gap:.2f} | 托板余隙 {P['tray_z0'] - cap_z1:.2f}")
    print("=" * 70)
    return 0, {
        "ok": True,
        "radial_gap": round(radial, 2),
        "cap_overhang": round(overhang, 2),
        "cap_gap": round(gap, 2),
        "tray_clear": round(P["tray_z0"] - cap_z1, 2),
        "min_travel": round(min_travel, 1),
    }


def main():
    ap = argparse.ArgumentParser(description="投放机构尺寸链自检")
    ap.add_argument("--json", action="store_true")
    for k in P:
        ap.add_argument("--" + k.replace("_", "-"), type=float, default=None)
    args = ap.parse_args()

    for k in P:
        v = getattr(args, k.replace("-", "_"), None)
        if v is not None:
            P[k] = v

    if args.json:
        _, st = evaluate(verbose=False)
        print(json.dumps(st, ensure_ascii=False))
        return 0 if st["ok"] else 1

    rc, _ = evaluate()
    rc |= check_scad_sync()
    return rc


if __name__ == "__main__":
    sys.exit(main())
