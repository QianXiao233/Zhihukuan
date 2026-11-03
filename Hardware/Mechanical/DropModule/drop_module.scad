// =============================================================================
// 无人艇投放模块 —— 舵机开口锁扣 + 倒扣圆盘（v4，五金版）
//
// 机构原理
//   MG90S 竖直安装、输出轴朝上。轴上摇臂带一根竖直销轴；托板下方的耳板
//   在靠后的边缘开一个半圆缺口，销轴柱段就卡在缺口里。
//   销轴顶端拧一个独立的倒扣圆盘，圆盘悬在耳板上方 0.1 mm。
//
//   载荷把托板前端压下 -> 托板绕铰链转 -> 耳板向后上方逃 -> 被圆盘挡住。
//   舵机转 90° 把销轴摆出缺口 -> 耳板失去依托 -> 托板前翻 -> 载荷落水。
//
// 为什么是"开口缺口"而不是通孔
//   通孔方案里销轴退出时要穿过耳板板厚区。按 3° 步长扫 0~90°，
//   销轴在 21°~48° 一直压在耳板实体上，装配后卡着走、表现为"舵机动了但托板不翻"。
//   开口缺口让销轴沿开口直接滑出，扫描显示 0.5° 起就完全离开。
//
// 为什么必须加倒扣圆盘
//   竖直销轴只能挡**平面内**的位移。托板绕铰链转时，耳板那一点的位移
//   几乎全是竖直的（半径向量近水平、切向近竖直），所以托板会沿销轴往上滑脱。
//   圆盘 Ø12 比缺口 Ø5.9 大，悬在耳板上方 —— 托板往上逃就顶在圆盘下表面。
//
// 为什么圆盘是独立零件
//   圆盘比缺口大，一体打印的话耳板装不进去（销轴没法穿过缺口）。
//   所以圆盘单独打印，最后用 M2 自攻螺丝拧到销轴顶端的孔上。
//
// Z 向尺寸链
//   z=0          甲板/支架底面
//   3..25.5      舵机机身
//   25.5..28.5   摇臂
//   28.5..34.5   销轴柱段（穿过耳板）
//   30.9..34.4   耳板
//   34.5..35.35  倒扣圆盘（独立件，M2 螺丝）
//   35.5..39.5   托板
// =============================================================================

/* [选择导出] */
PART = "assembly";   // [assembly, bracket, horn, tray_ear, cap, tray, explode]

/* [精度] */
$fn = 48;

// -----------------------------------------------------------------------------
// PARAMS —— 与 verify_geometry.py / check_pin_sweep.py 一一对应
// -----------------------------------------------------------------------------
// ---- MG90S 机身 ----
SERVO_L   = 22.8;    // 机身长（y）
SERVO_W   = 12.2;    // 机身宽（x）
SERVO_H   = 22.5;    // 机身高（z）
SHAFT_OFF = 3.5;     // 输出轴距机身近端（y）
GEAR_D    = 4.9;     // 输出齿盘直径

// ---- 摇臂与销轴 ----
HORN_T   = 3.0;
BOSS_D   = 10.0;
HORN_W   = 7.0;
PIN_R    = 15.0;     // 销轴中心到舵机轴距离
PIN_D    = 5.0;
PIN_TOP  = 34.5;     // 柱段顶端 = 圆盘底面
PIN_CH   = 1.0;      // 顶端倒角

// ---- 倒扣圆盘（独立件）----
CAP_D    = 12.0;
CAP_T    = 0.85;
M2_D     = 2.2;      // 自攻螺孔
M2HY_D   = 4.0;      // 螺丝头沉孔

// ---- 弹簧柱 ----
SPRING_R = 1.6;
SPRING_X = -12.5;
SPRING_Z = 27.0;

// ---- 支架 ----
WALL_T     = 3.0;
BASE_T     = 3.0;
SERVO_CLR  = 0.4;
SCREW_D    = 2.2;
FLANGE_Y0  = 3.0;
FLANGE_Y1  = 14.0;
WALL_H     = 18.0;

// ---- 托板耳板（开口缺口）----
EAR_T     = 3.5;
EAR_NOTCH = 5.9;     // 缺口直径（销轴 5.0 + 0.9）
EAR_X0    = -4.0;
EAR_X1    = 25.0;
EAR_Y0    = -11.0;
EAR_Y1    = 3.5;     // 缺口开在这条边
EAR_Z1    = 34.4;
EAR_Z0    = EAR_Z1 - EAR_T;

// ---- 托板 ----
TRAY_X0 = -70.0;
TRAY_X1 = 25.0;
TRAY_FRONT_Y = -42.0;
TRAY_BACK_Y  = 14.0;
TRAY_T  = 4.0;

// ---- 铰链 ----
HINGE_Y = 14.0;
HINGE_Z = 35.5;

// ---- 舵机轴 ----
AXIS_X = 0;
AXIS_Y = SHAFT_OFF;

// ---- 行程 ----
SERVO_TRAVEL_DEG = 90;
TRAY_DUMP_DEG    = 30;

EPS = 0.01;

// -----------------------------------------------------------------------------
// 派生 Z 栈
// -----------------------------------------------------------------------------
BODY_Z0 = BASE_T;                  // 3
BODY_Z1 = BASE_T + SERVO_H;        // 25.5
HORN_Z0 = BODY_Z1;
HORN_Z1 = HORN_Z0 + HORN_T;        // 28.5
CAP_Z0  = PIN_TOP;                 // 34.5
CAP_Z1  = CAP_Z0 + CAP_T;          // 35.35
TRAY_Z0 = HINGE_Z;                 // 35.5
TRAY_Z1 = TRAY_Z0 + TRAY_T;        // 39.5

// =============================================================================
// 舵机支架：U 形槽承托机身，两侧壁开安装耳槽，底板 4 个 M2 孔
// =============================================================================
module bracket() {
    xo = SERVO_W / 2 + SERVO_CLR;           // 侧壁内表面 x
    y0 = -2;
    y1 = SERVO_L + 2;
    // 底板向左(-x)延伸到弹簧柱之外，否则弹簧柱会悬空，
    // CGAL 会把它算成独立实体（打印出来是个掉件）。
    x_base0 = -16.0;

    difference() {
        union() {
            // 底板
            translate([x_base0, y0, 0])
                cube([xo + WALL_T + 9.0 - x_base0, y1 - y0, BASE_T]);
            // 两侧壁
            for (sx = [-1, 1])
                translate([sx > 0 ? xo : -xo - WALL_T, y0, 0])
                    cube([WALL_T, y1 - y0, WALL_H]);
            // 后端挡壁
            translate([-xo - WALL_T, y1 - 1.5, 0])
                cube([2 * xo + 2 * WALL_T, 1.5, WALL_H]);
            // 弹簧柱：从 z=0 起，与底板连成一体
            translate([SPRING_X, AXIS_Y, 0])
                cylinder(r = SPRING_R, h = SPRING_Z);
        }

        // 安装耳槽：侧壁上开水平口，舵机的耳朵卡进来
        for (sx = [-1, 1])
            translate([sx > 0 ? xo - EPS : -xo - WALL_T - EPS,
                       FLANGE_Y0, HORN_Z1 - 4.0])
                cube([WALL_T + 2 * EPS, FLANGE_Y1 - FLANGE_Y0, 6.5]);

        // 甲板安装孔：开在侧壁之外的底板外伸处。
        // 早先开在 x=±(xo+WALL_T/2)，正好落在侧壁实体下面，孔打不穿。
        for (sx = [-1, 1], sy = [-1, 1])
            translate([sx * (xo + WALL_T + 4.0),
                       (sy < 0 ? y0 + 5 : y1 - 5), -EPS])
                cylinder(d = SCREW_D, h = BASE_T + 2 * EPS);

        // 走线缺口
        translate([-xo - WALL_T - EPS, y1 - 12, BASE_T + 2])
            cube([2 * xo + 2 * WALL_T + 2 * EPS, 6, 20]);
    }
}

// =============================================================================
// 摇臂 + 销轴（一体打印）
// =============================================================================
module horn() {
    translate([AXIS_X, AXIS_Y, HORN_Z0]) {
        difference() {
            union() {
                hull() {
                    cylinder(d = BOSS_D, h = HORN_T);
                    translate([PIN_R, 0, 0]) cylinder(d = HORN_W, h = HORN_T);
                }
                hull() {
                    cylinder(d = BOSS_D, h = HORN_T);
                    translate([SPRING_X + 2, 0, 0]) cylinder(d = HORN_W - 1, h = HORN_T);
                }
            }
            // 齿盘孔
            translate([0, 0, -EPS])
                cylinder(d = GEAR_D + 0.2, h = HORN_T + 2 * EPS);
            // 中心螺丝孔
            translate([0, 0, -EPS]) cylinder(d = 2.2, h = HORN_T + 2 * EPS);
            // 弹簧柱让位
            translate([SPRING_X, 0, -EPS]) cylinder(r = SPRING_R + 0.5, h = HORN_T + 2 * EPS);
        }
        // 销轴柱段 + 顶端 M2 螺孔（供倒扣圆盘固定）
        translate([PIN_R, 0, 0])
            difference() {
                union() {
                    cylinder(d = PIN_D, h = PIN_TOP - HORN_Z0 - PIN_CH);
                    translate([0, 0, PIN_TOP - HORN_Z0 - PIN_CH])
                        cylinder(d1 = PIN_D, d2 = PIN_D - 2 * PIN_CH, h = PIN_CH);
                }
                // M2 自攻孔，深 6（柱段长 6，能咬住）
                translate([0, 0, PIN_TOP - HORN_Z0 - 6.5])
                    cylinder(d = M2_D, h = 7);
            }
    }
}

// =============================================================================
// 倒扣圆盘（独立件）：卡住耳板上方，阻止托板沿销轴向上逃逸
// =============================================================================
module cap() {
    difference() {
        translate([0, 0, CAP_Z0])
            cylinder(d = CAP_D, h = CAP_T);
        // 中心螺丝孔（M2 自攻，Ø2.2）
        translate([0, 0, CAP_Z0 - EPS])
            cylinder(d = M2_D - 0.1, h = CAP_T + 2 * EPS);
        // 螺丝头沉孔
        translate([0, 0, CAP_Z1 - 0.9])
            cylinder(d = M2HY_D, h = 0.9 + EPS);
        // 底面减重槽
        translate([0, 0, CAP_Z0 - EPS])
            cylinder(d = CAP_D - 3.0, h = 0.15);
    }
}

// =============================================================================
// 托板耳板：靠后边(y=EAR_Y1)开半圆缺口
//
// 关键约束：缺口必须**开口**（在板边），不能是通孔。
// 通孔会让销轴退出时穿过板厚区 —— 实测在 21°~48° 卡死。
// =============================================================================
module tray_ear() {
    difference() {
        translate([EAR_X0, EAR_Y0, EAR_Z0])
            cube([EAR_X1 - EAR_X0, EAR_Y1 - EAR_Y0, EAR_T]);
        // 开口缺口：圆心落在板边上，只切出半圆
        translate([PIN_R, EAR_Y1, EAR_Z0 - EPS])
            cylinder(d = EAR_NOTCH, h = EAR_T + 2 * EPS);
    }
    // 与托板的连接筋（把耳板吊在托板底面下）
    translate([EAR_X0 + 2, EAR_Y1 - 11, EAR_Z1])
        cube([EAR_X1 - EAR_X0 - 4, 11, TRAY_Z0 - EAR_Z1]);
}

// =============================================================================
// 演示托板
// =============================================================================
module tray() {
    difference() {
        union() {
            translate([TRAY_X0, TRAY_FRONT_Y, TRAY_Z0])
                cube([TRAY_X1 - TRAY_X0, TRAY_BACK_Y - TRAY_FRONT_Y, TRAY_T]);
            // 前唇（防止载荷前滑落）
            translate([TRAY_X0, TRAY_FRONT_Y, TRAY_Z1])
                cube([TRAY_X1 - TRAY_X0, 5, 6]);
        }
        for (i = [0, 1])
            translate([TRAY_X0 + 20 + i * 30, TRAY_FRONT_Y + 18, TRAY_Z0 - EPS])
                cylinder(d = 12, h = TRAY_T + 2 * EPS);
    }
}

// =============================================================================
// 装配
// =============================================================================
module assembly(exploded = false) {
    E = exploded ? 22 : 0;

    color("#8a9099") bracket();
    color("#2b3038") {
        translate([-SERVO_W / 2, 0, BODY_Z0]) cube([SERVO_W, SERVO_L, SERVO_H]);
        translate([AXIS_X, AXIS_Y, BODY_Z1]) cylinder(d = GEAR_D, h = 2.2);
    }
    color("#2f86e8") horn();
    // 倒扣圆盘（独立件，M2 螺丝固定）
    translate([AXIS_X + PIN_R, AXIS_Y, E])
        color("#7cc0ff") cap();
    color("#ef9d2e") tray_ear();
    translate([0, 0, E * 0.8]) color("#c6cdd8") tray();
}

// =============================================================================
// 导出选择。RENDER_MAIN 让 include 时不重复渲染
// =============================================================================
RENDER_MAIN = is_undef(_DM_INCLUDED) ? 1 : 0;

if (RENDER_MAIN) {
    if (PART == "bracket")       bracket();
    else if (PART == "horn")     horn();
    else if (PART == "tray_ear") tray_ear();
    else if (PART == "cap")      cap();
    else if (PART == "tray")     tray();
    else if (PART == "explode")  assembly(true);
    else                         assembly(false);
}
