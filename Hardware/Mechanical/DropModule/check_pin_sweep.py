#!/usr/bin/env python3
"""
销轴摆出路径扫描 + 竖直逃逸检查

两个必须查清楚的问题
--------------------
1. 摆出路径干涉：销轴从耳板缺口里摆出来时，会不会一路蹭着耳板走？
   用"销轴圆盘 ∩ 耳板实体"逐角度采样判定。

2. **竖直逃逸（这是致命的一条）**
   一根竖直销轴插在水平板的孔里，只能约束板的**平面内**运动。
   托板绕铰链转时，耳板那一点是沿圆弧走的，位移几乎全是竖直方向 ——
   于是托板可以直接沿销轴往上"滑脱"，销轴一点都挡不住。

   所以必须加一个**倒扣头**：销轴顶端做一个比缺口大的圆盘，
   它悬在耳板顶面之上。托板往上逃时，耳板顶面顶在圆盘下表面上，
   被挡住。这就是本项目最终采用的"倒扣销"。

本脚本同时验证这两条。
"""

import math
import sys

# 与 drop_module.scad 一致
AXIS_Y     = 3.5
PIN_R      = 15.0
PIN_D      = 5.0
EAR_NOTCH  = 5.9
EAR_X0     = -2.0
EAR_X1     = 26.0
EAR_Y0     = -10.0
EAR_Y1     = 3.5
EAR_T      = 3.5
EAR_Z1     = 34.4          # 耳板顶面
EAR_Z0     = EAR_Z1 - EAR_T
HORN_Z1    = 28.5
SHAFT_TOP  = 34.5          # 销轴柱段顶端 = 倒扣头底面
HEAD_Z0    = 34.5
HEAD_Z1    = 35.35
HEAD_D     = 12.0
TRAY_Z0    = 35.5
TRAY_DUMP  = 30.0
HINGE_Y    = 14.0
HINGE_Z    = 35.5

NOTCH_R = EAR_NOTCH / 2.0
PR      = PIN_D / 2.0
HEAD_R  = HEAD_D / 2.0


def pin_y(deg):
    """俯视图里销轴中心的 y 坐标（x 方向的分量不影响侧视判断）"""
    return AXIS_Y + PIN_R * math.sin(math.radians(deg))


def pin_x(deg):
    return PIN_R * math.cos(math.radians(deg))


def in_rect(x, y):
    return EAR_X0 <= x <= EAR_X1 and EAR_Y0 <= y <= EAR_Y1


def in_notch(x, y):
    return math.hypot(x - PIN_R, y - EAR_Y1) <= NOTCH_R


def sweep_check():
    """逐角度采样：销轴圆盘是否压到耳板的实体部分"""
    bad = []
    first_clear = None
    for a10 in range(0, 901, 5):
        a = a10 / 10.0
        cx, cy = pin_x(a), pin_y(a)
        hit = False
        # 在销轴圆盘内采样
        n = 14
        for i in range(n + 1):
            for j in range(n + 1):
                dx = -PR + 2 * PR * i / n
                dy = -PR + 2 * PR * j / n
                if dx * dx + dy * dy > PR * PR:
                    continue
                px, py = cx + dx, cy + dy
                if in_rect(px, py) and not in_notch(px, py):
                    hit = True
                    break
            if hit:
                break
        if hit:
            bad.append(a)
        else:
            if first_clear is None and a > 0:
                first_clear = a
    return bad, first_clear


def escape_check():
    """竖直逃逸：倒扣头必须比缺口大，且在耳板顶面之上"""
    head_overhang = (HEAD_R - NOTCH_R)
    gap = HEAD_Z0 - EAR_Z1
    tray_clear = TRAY_Z0 - HEAD_Z1
    ok = True

    print("\n[2] 竖直逃逸检查（倒扣头）")
    if head_overhang > 0:
        print(f"  [OK] 倒扣头 Ø{HEAD_D:.1f} 比缺口 Ø{EAR_NOTCH:.1f} 大，"
              f"单边外伸 {head_overhang:.2f} mm")
        print(f"       耳板顶面被圆盘下表面挡住，托板无法沿销轴向上逃逸")
    else:
        print(f"  [x] 倒扣头 Ø{HEAD_D:.1f} 不大于缺口 Ø{EAR_NOTCH:.1f}，挡不住")
        ok = False

    if 0 < gap <= 0.25:
        print(f"  [OK] 圆盘底面与耳板顶面间隙 {gap:.2f} mm（贴而不磨）")
    else:
        print(f"  [x] 圆盘底面与耳板顶面间隙 {gap:.2f} mm，应为 0~0.25")
        ok = False

    if tray_clear >= 0.1:
        print(f"  [OK] 圆盘顶面与托板底面间隙 {tray_clear:.2f} mm"
              f"（任何转角都不磨托板）")
    else:
        print(f"  [x] 圆盘顶 z={HEAD_Z1} 顶到托板底 z={TRAY_Z0}")
        ok = False

    # 柱段要穿过整个耳板厚度
    if SHAFT_TOP >= EAR_Z1:
        print(f"  [OK] 柱段穿过耳板全厚（{EAR_Z0:.1f}~{EAR_Z1:.1f}）")
    else:
        print(f"  [x] 柱段顶 {SHAFT_TOP} 低于耳板顶 {EAR_Z1}，插不透")
        ok = False
    return ok


def tray_kinematics():
    """托板转起来后，耳板缺口处会不会撞到倒扣头"""
    print(f"\n[3] 托板翻转 {TRAY_DUMP:.0f}° 时的耳板/圆盘关系")
    # 耳板缺口中心相对铰链
    dy = EAR_Y1 - HINGE_Y
    dz = EAR_Z1 - HINGE_Z
    th = math.radians(TRAY_DUMP)
    # 前(-y)下沉 = 绕 +x 逆时针（在 y 向右、z 向上的平面里）
    # 标准旋转：y' = y·cosθ - z·sinθ,  z' = y·sinθ + z·cosθ
    # （这里 y、z 都是相对铰链的偏移量）
    ny = HINGE_Y + dy * math.cos(th) - dz * math.sin(th)
    nz = HINGE_Z + dy * math.sin(th) + dz * math.cos(th)
    print(f"  缺口中心从 (y={EAR_Y1}, z={EAR_Z1}) 转到 "
          f"(y={ny:.2f}, z={nz:.2f})")
    drop = EAR_Z1 - nz
    print(f"  下沉 {drop:.2f} mm")
    if drop > 0.5:
        print("  [OK] 耳板确实下沉离开圆盘，释放动作成立")
        return True
    print("  [x] 耳板没有下沉，托板不会翻")
    return False


def check_scad_sync():
    """核对 .scad 里的关键 Z 参数，防止改了模型忘了改这里"""
    import re
    from pathlib import Path
    scad = Path(__file__).with_name("drop_module.scad")
    if not scad.exists():
        print("\n[跳过] 找不到 drop_module.scad")
        return 0
    text = scad.read_text(encoding="utf-8", errors="replace")
    expect = {
        "PIN_R": PIN_R, "PIN_D": PIN_D, "EAR_NOTCH": EAR_NOTCH,
        "EAR_Z1": EAR_Z1, "HEAD_D": HEAD_D, "HINGE_Y": HINGE_Y,
    }
    # 注意 CAP_Z0 / TRAY_Z0 在 .scad 里是**派生量**（CAP_Z0=PIN_TOP、
    # TRAY_Z0=HINGE_Z），不是字面量，所以不参与对账。
    print("\n[校验] 与 drop_module.scad 的一致性")
    drift = 0
    for macro, want in expect.items():
        # .scad 里倒扣圆盘叫 CAP_D / CAP_Z0，这里映射一下
        pat = {"HEAD_D": "CAP_D", "HEAD_Z0": "CAP_Z0"}.get(macro, macro)
        m = re.search(rf"^{pat}\s*=\s*([\d.]+)", text, re.M)
        if not m:
            print(f"  [??] 未找到 {pat}")
            continue
        val = float(m.group(1))
        if abs(val - want) < 1e-6:
            print(f"  [ OK ] {pat} = {val}")
        else:
            print(f"  [x] {pat}: .scad={val} 但脚本={want}")
            drift += 1
    return 0 if drift == 0 else 1


def main():
    print("销轴摆出路径 + 竖直逃逸检查（倒扣销方案）")
    print(f"  缺口中 (x={PIN_R}, y={EAR_Y1})，Ø{EAR_NOTCH}")
    print(f"  倒扣头 Ø{HEAD_D}，z {HEAD_Z0}~{HEAD_Z1}，托板底 z={TRAY_Z0}")
    print(f"\n[1] 摆出路径（销轴柱段 vs 耳板实体）")

    bad, first_clear = sweep_check()
    if bad:
        print(f"  [x] {len(bad)} 个角度压到耳板：{bad[0]}° ~ {bad[-1]}°")
        print(f"      前几个：{bad[:8]}")
        rc = 1
    else:
        print(f"  [OK] 全程无干涉；销轴在 {first_clear}° 起完全离开耳板")
        rc = 0

    ok = escape_check()
    ok2 = tray_kinematics()

    print("\n" + "=" * 66)
    if rc == 0 and ok and ok2:
        print("全部通过：可以按这个方案建模与装配")
    else:
        print("存在未通过项，先修几何再打印")
    print("=" * 66)
    return 0 if (rc == 0 and ok and ok2) else 1


if __name__ == "__main__":
    rc = main()
    rc |= check_scad_sync()
    sys.exit(rc)
