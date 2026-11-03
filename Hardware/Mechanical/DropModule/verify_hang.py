#!/usr/bin/env python3
"""
悬挂版（v5）—— 下垂悬臂 + 舵机托举

机构
----
一根悬臂（吊杆）铰接在船头，平时略微上扬。救生圈的挂环套在杆上，
靠自重压着杆往下走 —— 但杆被舵机摇臂从下方托住，所以掉不下去。

舵机转 90° 把摇臂让开 -> 悬臂失去支撑 -> 绕铰链垂下去 ->
挂环沿杆滑到末端脱出 -> 救生圈落水。

为什么不是"挡块挡住挂环"
------------------------
挂环套在杆上，要挡住它，阻止件必须在**杆的末端之外**；可杆又必须在那里
结束（否则挂环出不来）。挡块若要转开，转动过程中必然与杆相交。
这是"套环 + 转动挡块"的固有矛盾，我扫描过参数，无解。

改成"让杆本身垂下去"，就没有这个矛盾了：杆往下走，挂环跟着滑到末端，
末端之外是空的，直接掉出。

本脚本验证什么
--------------
  1. 力矩：舵机托举力够不够、占堵转多少
  2. 挂环位置：静止时确实挂在杆上、且位于船外
  3. 下垂后：挂环能滑到杆末端之外（有足够行程）
  4. 扫掠：摇臂转开时碰不到悬臂和挂环

坐标（mm）
----------
  y : +y 朝船内，-y 朝船头外
  z : 0 = 甲板面，+z 向上
  x : 舵机轴与悬臂铰链的轴向
"""

import math
import sys

# ---- 舵机 ----
SERVO_H   = 22.5
BASE_T    = 3.0
SERVO_L   = 22.8
SHAFT_OFF = 3.5
SERVO_Y   = 18.0                  # 舵机轴 y（在船内）
SERVO_Z   = BASE_T + SERVO_H      # 25.5 机身顶
HORN_T    = 3.0
HORN_Z    = SERVO_Z               # 摇臂底面 25.5
STALL_NM  = 1.8 * 0.098           # 0.176 N·m

# ---- 悬臂（吊杆）----
PIVOT_Y   = 4.0                   # 铰链 y（在船头甲板边缘内侧）
PIVOT_Z   = 46.0                  # 铰链高度
BOOM_OUT  = -48.0                 # 杆外端 y（伸出船头）
BOOM_IN   = 20.0                  # 杆内端 y（伸到舵机上方）
BOOM_D    = 8.0                   # 杆直径
BOOM_TILT = 6.0                   # 静止时上扬角（度）

# ---- 挂环 / 载荷 ----
LOOP_IN   = 20.0                  # 挂环内径
LOOP_TH   = 4.0                   # 环材直径（绳/钢丝）
LOAD_G    = 150.0                 # 救生圈 + 挂环质量
BOOM_MASS = 30.0                  # 悬臂自身质量（估）

HULL_EDGE = 0.0                   # 船头边缘
DROP_ANGLE = 40.0                 # 释放后下垂角


def boom_z(y):
    """悬臂中心线在给定 y 处的 z（静止、上扬状态）"""
    return PIVOT_Z + (PIVOT_Y - y) * math.tan(math.radians(BOOM_TILT))


def check():
    fails, oks = [], []

    def ck(name, cond, detail):
        (oks if cond else fails).append((name, detail))
        print(("  [ OK ] " if cond else "  [FAIL] ") + f"{name}: {detail}")

    print("悬挂版验证：下垂悬臂 + 舵机托举")
    print(f"  铰链 (y={PIVOT_Y}, z={PIVOT_Z})，上扬 {BOOM_TILT}°")
    print(f"  悬臂 y {BOOM_OUT}..{BOOM_IN}，Ø{BOOM_D}")
    print(f"  舵机轴 y={SERVO_Y}，摇臂 z={HORN_Z}..{HORN_Z + HORN_T}")
    print(f"  挂环内径 Ø{LOOP_IN}，载荷 {LOAD_G} g")

    # 静止时杆的端点高度
    z_out = boom_z(BOOM_OUT)
    z_in = boom_z(BOOM_IN)
    print(f"  杆外端 z={z_out:.1f}，内端 z={z_in:.1f}")

    # ---------- 1. 挂环静止位置 ----------
    print("\n[1] 挂环静止位置")
    # 挂环靠自重停在杆上，位置取决于是否被摇臂挡住。
    # 这里让它停在"摇臂正上方"，即 y ≈ SERVO_Y
    LOOP_Y = SERVO_Y
    z_boom_at_loop = boom_z(LOOP_Y)
    print(f"    挂环停在 y={LOOP_Y}，该处杆心 z={z_boom_at_loop:.1f}")
    ck("挂环位于船头之外（能落进水里）", LOOP_Y < HULL_EDGE,
       f"y={LOOP_Y} < {HULL_EDGE}")
    # 挂环下垂后最底点
    loop_bottom = z_boom_at_loop - (LOOP_IN / 2 + LOOP_TH)
    ck("挂环底端低于摇臂顶面（摇臂能托住杆）",
       loop_bottom < HORN_Z + HORN_T,
       f"挂环底 {loop_bottom:.1f} vs 摇臂顶 {HORN_Z + HORN_T:.1f}")

    # ---------- 2. 力矩：舵机要托住多少 ----------
    print("\n[2] 舵机托举力矩")
    # 悬臂自重 + 载荷，对铰链取矩
    m_boom = BOOM_MASS * (PIVOT_Y - (BOOM_OUT + PIVOT_Y) / 2)
    m_load = LOAD_G * (PIVOT_Y - LOOP_Y)
    m_total = m_boom + m_load            # g·mm
    print(f"    悬臂自重对铰链矩 {m_boom:.0f} g·mm")
    print(f"    载荷对铰链矩   {m_load:.0f} g·mm")
    print(f"    合计 {m_total:.0f} g·mm = {m_total / 1020:.4f} N·m")

    # 内端需要多大的支撑力
    arm_in = PIVOT_Y - BOOM_IN           # 内端到铰链距离
    arm_in = abs(BOOM_IN - PIVOT_Y)
    F_support = m_total / arm_in         # g
    print(f"    内端支撑力 = {m_total:.0f}/{arm_in:.0f} = {F_support:.0f} g "
          f"= {F_support * 9.8 / 1000:.2f} N")

    # 支撑点若在摇臂上，离舵机轴的水平距离决定扭矩
    contact_y = BOOM_IN                  # 支撑点在内端
    r_contact = abs(contact_y - SERVO_Y)  # 到舵机轴距离
    print(f"    支撑点在 y={contact_y}，距舵机轴 {r_contact:.1f} mm")
    tq = F_support * 9.8 / 1000 * (r_contact / 1000.0)
    print(f"    摇臂需承担扭矩 {tq:.4f} N·m（占堵转 {tq / STALL_NM * 100:.0f}%）")
    ck("舵机扭矩余量 < 40% 堵转", tq < STALL_NM * 0.4,
       f"{tq / STALL_NM * 100:.0f}%")

    # ---------- 3. 释放后挂环能滑出去 ----------
    print("\n[3] 释放：悬臂下垂后挂环能否脱出")
    # 下垂 DROP_ANGLE 后，杆外端更低；挂环沿杆滑到末端
    ang = math.radians(DROP_ANGLE)
    # 杆上任意点距铰链的距离
    dist_loop = abs(PIVOT_Y - LOOP_Y)
    dist_tip = abs(PIVOT_Y - BOOM_OUT)
    slide = dist_tip - dist_loop
    print(f"    挂环距铰链 {dist_loop:.0f} mm，杆末端距铰链 {dist_tip:.0f} mm")
    print(f"    需滑行 {slide:.0f} mm 才到末端")
    ck("滑行距离足够（>= 挂环半径）", slide >= LOOP_IN / 2,
       f"{slide:.0f} mm >= {LOOP_IN / 2:.0f} mm")

    # 下垂后末端高度（要低于挂环原来位置，形成落差）
    z_tip_drop = PIVOT_Z - dist_tip * math.sin(ang)
    print(f"    下垂 {DROP_ANGLE}° 后末端 z={z_tip_drop:.1f}"
          f"（原 {z_out:.1f}，落差 {z_out - z_tip_drop:.1f} mm）")
    ck("下垂后形成足够落差（>=20 mm），靠重力即可滑出",
       (z_out - z_tip_drop) >= 20,
       f"落差 {z_out - z_tip_drop:.1f} mm")

    # ---------- 4. 摇臂扫掠不碰悬臂 ----------
    print("\n[4] 摇臂扫掠 vs 悬臂")
    # 摇臂在 z 25.5..28.5 的水平面内摆；悬臂在其上方
    # 悬臂内端最低点
    z_in_bottom = z_in - BOOM_D / 2
    ck("悬臂内端底面高于摇臂顶面（否则摆臂会撞杆）",
       z_in_bottom > HORN_Z + HORN_T,
       f"杆内端底 {z_in_bottom:.1f} vs 摇臂顶 {HORN_Z + HORN_T:.1f}，"
       f"间隙 {z_in_bottom - (HORN_Z + HORN_T):.1f} mm")

    # 摇臂半径要够到内端
    HORN_R = abs(BOOM_IN - SERVO_Y) + 4
    print(f"    摇臂半径需 >= {abs(BOOM_IN - SERVO_Y):.0f} mm（够到内端），"
          f"取 {HORN_R:.0f} mm")
    ck("摇臂半径合理（<= 25 mm，MG90S 可驱动）", HORN_R <= 25,
       f"R={HORN_R:.0f} mm")

    print("\n" + "=" * 70)
    if fails:
        print(f"结果：{len(fails)} 项不通过 / {len(oks)} 项通过")
        for n, d in fails:
            print(f"  [x] {n} -- {d}")
        print("=" * 70)
        return 1
    print(f"结果：全部 {len(oks)} 项通过")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(check())
