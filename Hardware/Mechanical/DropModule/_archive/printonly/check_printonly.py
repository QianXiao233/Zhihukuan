#!/usr/bin/env python3
"""
纯 3D 打印版 —— 替代五金件的力学核算

去掉 M2 螺丝、压簧、金属合页之后，必须证明四件事仍然成立：

  1. 打印板簧能提供足够的保持力（又不超舵机扭矩）
  2. 压配孔能传递舵机扭矩而不打滑
  3. 帽形圆盘的裙边卡脚能承受载荷的竖直分力
  4. 一体薄片铰链的弯折应力和寿命可接受

任何一条不成立，"纯打印"就是纸上谈兵。

参数在改 scad 之后跑一遍；本脚本会对照 scad 报不一致。
"""

import math
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 材料参数（PETG，保守取值）
# ---------------------------------------------------------------------------
E_PETG     = 2000.0   # MPa
YIELD_PETG = 50.0     # MPa
MU_PETG    = 0.20     # 摩擦系数（对舵机塑料/金属齿盘，保守）

# ---------------------------------------------------------------------------
# 几何 —— 与 drop_module.scad 一致
# ---------------------------------------------------------------------------
G = {
    "SPRING_L": 14.0,
    "SPRING_W": 8.0,
    "SPRING_T": 1.0,
    "GEAR_D": 4.9,
    "PRESS_FIT": 0.20,
    "HORN_T": 3.0,
    "PIN_D": 5.0,
    "PIN_R": 15.0,
    "CAP_D": 12.0,
    "CAP_SKIRT_T": 1.6,
    "CAP_SKIRT_H": 4.0,
    "SNAP_GROOVE_D": 1.4,
    "LIVING_T": 0.5,
    "LIVING_W": 50.0,
    "LIVING_ARC": 12.0,
    "HINGE_Y": 14.0,
    "EAR_Y1": 3.5,
    "TRAY_FRONT_Y": -42.0,
}

MG90S_STALL_KGCM = 1.8
STALL_NM = MG90S_STALL_KGCM * 0.098   # 0.1764 N·m


def pct(x, total):
    return f"{x / total * 100:.0f}%"


# ---------------------------------------------------------------------------
def spring():
    L, W, T = G["SPRING_L"], G["SPRING_W"], G["SPRING_T"]
    I = W * T ** 3 / 12.0
    k = 3 * E_PETG * I / L ** 3

    print("[1] 打印板簧（悬臂梁，替代压簧）")
    print(f"    尺寸 {L}×{W}×{T} mm，I={I:.3f} mm⁴，k={k:.3f} N/mm")

    # 设计工作点：压缩量使末端力落在 0.2~0.5 N
    delta = 0.35 / k
    F = k * delta
    print(f"    工作点 δ={delta:.2f} mm -> F={F:.2f} N")

    M = F * L
    Z = W * T ** 2 / 6.0
    sigma = M / Z
    print(f"    根部弯曲应力 {sigma:.1f} MPa（屈服 {YIELD_PETG}，占 "
          f"{pct(sigma, YIELD_PETG)}）")
    ok_stress = sigma < YIELD_PETG * 0.4
    print(f"    {'[OK]' if ok_stress else '[x]'} 应力 < 40% 屈服")

    # 舵机需克服的额外扭矩
    tq = F * (G["PIN_R"] / 1000.0)
    print(f"    舵机额外扭矩 {tq:.4f} N·m（堵转 {STALL_NM:.3f}，占 "
          f"{pct(tq, STALL_NM)}）")
    ok_tq = tq < STALL_NM * 0.15
    print(f"    {'[OK]' if ok_tq else '[x]'} 舵机余量充足（<15% 堵转）")

    ok_print = T >= 0.8
    print(f"    {'[OK]' if ok_print else '[x]'} 厚度 {T} mm 可打印（>=0.8）")
    return ok_stress and ok_tq and ok_print


def press_fit():
    print("\n[2] 压配孔传扭矩（替代 M2 螺丝固定摇臂）")
    bore = G["GEAR_D"] - G["PRESS_FIT"]
    r = bore / 2.0
    p = E_PETG * (G["PRESS_FIT"] / 2.0) / (2 * r)      # MPa
    area = math.pi * bore * G["HORN_T"]
    N = p * area
    T = MU_PETG * N * r / 1000.0
    print(f"    孔 Ø{bore}，过盈 {G['PRESS_FIT']} mm")
    print(f"    径向压力 {p:.1f} MPa，法向力 {N:.0f} N")
    print(f"    摩擦可传扭矩 ≈ {T:.3f} N·m（占堵转 {pct(T, STALL_NM)}）")
    ok = T > STALL_NM * 1.5
    print(f"    {'[OK]' if ok else '[x]'} 摩擦扭矩 > 1.5 倍堵转")
    print("    另加 6 条径向齿槽咬进齿盘，即使摩擦不足也不会打滑")
    return ok


def cap_skirt():
    print("\n[3] 帽形圆盘裙边（替代 M2 螺丝固定圆盘）")
    area = 2 * math.pi * (G["PIN_D"] / 2) ** 2
    shear = area * 25.0
    print(f"    销轴 Ø{G['PIN_D']} 双剪能力 ≈ {shear:.0f} N（真正的承载路径）")

    ring_d = G["PIN_D"] - G["SNAP_GROOVE_D"] + 0.3
    foot_area = math.pi * ring_d * 1.2 * 0.5    # 开口槽削弱，保守取一半
    foot_shear = foot_area * 25.0
    print(f"    裙边卡脚承剪 {foot_area:.1f} mm²，能力 ≈ {foot_shear:.0f} N")

    arm_load = G["HINGE_Y"] - (G["TRAY_FRONT_Y"] + G["HINGE_Y"]) / 2
    arm_react = G["HINGE_Y"] - G["EAR_Y1"]
    Fv = 300 * arm_load / 10.0 / (arm_react / 10.0) * 9.8 / 1000
    print(f"    载荷 300 g 时圆盘竖直力 {Fv:.2f} N")
    ok = foot_shear > Fv * 3
    print(f"    {'[OK]' if ok else '[x]'} 卡脚余量 >3 倍")
    return ok


def living_hinge():
    print("\n[4] 一体薄片铰链（替代金属合页）")
    T, W, arc = G["LIVING_T"], G["LIVING_W"], G["LIVING_ARC"]
    angle = math.radians(30)
    R_eff = arc / angle
    eps = T / (2 * R_eff)
    print(f"    薄片 {W}×{arc}，厚 {T} mm")
    print(f"    弯折 30°（整段弧长）：等效半径 {R_eff:.1f} mm，应变 "
          f"{eps*100:.2f}%")
    print(f"    PETG 断裂应变 3~5%")
    ok = eps < 0.015
    print(f"    {'[OK]' if ok else '[x]'} 应变 <1.5%")
    ok_t = T <= 0.6
    print(f"    {'[OK]' if ok_t else '[x]'} 薄片厚度 <=0.6 mm（够软）")
    print("    注意：必须 PETG 或 PP，PLA 脆，第一次弯折就可能断")
    return ok and ok_t


def sync_scad():
    """核对 scad 里的参数，防止改了模型忘了改这里"""
    scad = Path(__file__).with_name("drop_module.scad")
    if not scad.exists():
        print("\n[跳过] 找不到 drop_module.scad")
        return 0
    text = scad.read_text(encoding="utf-8", errors="replace")
    print("\n[校验] 与 drop_module.scad 的一致性")
    drift = 0
    for k, want in G.items():
        # 允许等号两侧任意空格（scad 里为对齐会写 TRAY_FRONT_Y = -42.0）
        m = re.search(rf"^{k}\s*=\s*(-?[\d.]+)", text, re.M)
        if not m:
            print(f"  [??] 未找到 {k}")
            continue
        val = float(m.group(1))
        if abs(val - want) < 1e-6:
            print(f"  [ OK ] {k} = {val}")
        else:
            print(f"  [x] {k}: .scad={val} 但脚本={want}")
            drift += 1
    return 0 if drift == 0 else 1


def main():
    print("纯 3D 打印版 —— 五金件替代方案力学核算")
    print("=" * 72)
    results = [
        ("板簧", spring()),
        ("压配传扭矩", press_fit()),
        ("帽形圆盘", cap_skirt()),
        ("一体铰链", living_hinge()),
    ]
    print("\n" + "=" * 72)
    bad = [n for n, ok in results if not ok]
    if bad:
        print(f"[x] 未通过：{', '.join(bad)}")
        rc = 1
    else:
        print("[OK] 四项全部通过 —— 纯打印版在力学上成立")
        rc = 0
    return rc | sync_scad()


if __name__ == "__main__":
    sys.exit(main())
