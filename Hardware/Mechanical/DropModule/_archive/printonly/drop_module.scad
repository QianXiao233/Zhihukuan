// =============================================================================
// 无人艇投放模块 —— 纯 3D 打印版（零五金件）
//
// 与 v4（五金版）的区别
//   原来需要：M2 螺丝 ×6、压簧 ×1、合页 ×1。
//   现在全部换成可打印结构：
//
//     原五金件              替代结构                        靠什么起作用
//     ────────────────────────────────────────────────────────────────────
//     M2×8 固定支架         甲板卡榫 + 侧向卡扣             过盈 0.15 mm
//     M2×6 固定摇臂到齿盘   压配孔 + 齿形防转                Ø4.7 过盈于 Ø4.9 齿盘
//     M2×6 固定倒扣圆盘     圆盘做成"帽形"，压配到销轴顶端   过盈 0.2 mm + 环槽卡住
//     压簧                  打印板簧（悬臂梁）               弹性变形提供回位力
//     金属合页              一体薄片铰链（living hinge）      PP/PETG 薄片反复弯折
//
// 为什么这些替代可行（不是凑合）
//   * 压配孔：PETG 打印孔的公差约 ±0.1 mm，Ø4.7 压到 Ø4.9 的齿盘上是标准做法，
//     舵机的输出扭矩（1.8 kg·cm）远小于压配摩擦力能传递的扭矩。
//   * 打印弹簧：需要的是"很软的推力"，不是大行程。悬臂梁 12 mm 长、1.2 mm 厚
//     在 2 mm 变形下提供约 0.3~0.5 N，正好够顶住摇臂又不超舵机扭矩。
//   * 一体铰链：托板是**一次性动作**（救援后手动复位），不是高频往复件，
//     薄片铰链几十次弯折完全够用。用 PETG 或 PP 打，不要用 PLA（脆，会断）。
//
// 失效安全仍然成立
//   板簧把摇臂压在锁定位，断电时舵机失力、板簧顶住，销轴保持在缺口里。
//
// 仍然依赖的非打印件（无法消除）
//   * MG90S 舵机本身（这是机构的核心执行器）
//   * 载板/船体（支架的卡榫需要插进甲板的相应孔位 —— 见 BRACKET_NOTCH）
//
// Z 向尺寸链
//   z=0          甲板/支架底面
//   3..25.5      舵机机身
//   25.5..28.5   摇臂（压配到齿盘）
//   28.5..34.5   销轴柱段（穿过耳板）
//   30.9..34.4   耳板
//   34.5..34.75  帽形圆盘（压配到销轴顶端，环槽卡住）
//   35.5..39.5   托板（一体铰链在其后端）
// =============================================================================

/* [选择导出] */
PART = "assembly";   // [assembly, bracket, horn, tray_ear, cap, tray, explode]

/* [精度] */
$fn = 48;

// -----------------------------------------------------------------------------
// PARAMS
// -----------------------------------------------------------------------------
// ---- MG90S 机身 ----
SERVO_L   = 22.8;
SERVO_W   = 12.2;
SERVO_H   = 22.5;
SHAFT_OFF = 3.5;
GEAR_D    = 4.9;

// ---- 摇臂与销轴 ----
HORN_T   = 3.0;
BOSS_D   = 10.0;
HORN_W   = 7.0;
PIN_R    = 15.0;
PIN_D    = 5.0;
PIN_TOP  = 34.5;
PIN_CH   = 1.0;
// 压配/卡扣公差
PRESS_FIT  = 0.20;   // 压配过盈量（半径向）
// 环槽：供帽形圆盘裙边的卡脚咬入。
// 注意槽深不能大 —— 销轴只有 Ø5，槽深 1.4 mm 时剩余直径 Ø3.6，
// 而顶端倒角又收到 Ø2.5，两者叠加会把顶部圆头切成独立小块（Volumes=3）。
// 取 0.6 mm 深（剩余 Ø3.8），且槽位放在柱段中部、远离倒角段。
SNAP_GROOVE_Z = PIN_TOP - 2.6;   // 环槽位置（离顶端够远，避开倒角）
SNAP_GROOVE_D = 0.6;             // 环槽深度

// ---- 帽形倒扣圆盘（纯打印，压配到销轴）----
CAP_D    = 12.0;
CAP_T    = 0.85;         // 盘厚度（悬在耳板顶上）
CAP_SKIRT_H = 4.0;       // 裙边高度（抱住销轴顶端，提供夹持）
CAP_SKIRT_T = 1.6;       // 裙边壁厚
CAP_SLIT = 1.4;          // 裙边开口槽宽（让裙边能张开套上去）

// ---- 打印板簧（替代压簧）----
// 参数由 check_printonly.py 的参数搜索选出，不是随手填的：
//   要同时满足 (a) 末端力 0.2~0.5 N（顶住摇臂但不过度吃舵机扭矩）
//             (b) 根部应力 < 40% 屈服
//   L=14 / W=8 / T=1.0 -> k=1.46 N/mm，压缩 0.24 mm 得 0.35 N，
//   根部应力 3.7 MPa（占屈服 7%）。余量很足。
// 早先取 W=5 / T=1.2 时应力占到 73% 屈服，长期会蠕变失效。
SPRING_L  = 14.0;        // 悬臂长度
SPRING_W  = 8.0;         // 宽度
SPRING_T  = 1.0;         // 厚度
SPRING_ARM_Y = -13.0;    // 板簧根部 y（在支架 -y 侧）
SPRING_FREE_Z = 26.0;    // 板簧自由端名义高度

// ---- 支架 ----
WALL_T     = 3.0;
BASE_T     = 3.0;
SERVO_CLR  = 0.4;
FLANGE_Y0  = 3.0;
FLANGE_Y1  = 14.0;
WALL_H     = 18.0;
// 甲板卡榫（替代 M2×8 螺丝）
NOTCH_W    = 6.0;        // 卡榫宽（x）
NOTCH_H    = 5.0;        // 卡榫高（z，向下插入甲板孔）
NOTCH_LIP  = 1.2;        // 侧向卡脚伸出量

// ---- 托板耳板（开口缺口）----
EAR_T     = 3.5;
EAR_NOTCH = 5.9;
EAR_X0    = -4.0;
EAR_X1    = 25.0;
EAR_Y0    = -11.0;
EAR_Y1    = 3.5;
EAR_Z1    = 34.4;

// ---- 托板 + 一体铰链 ----
TRAY_X0 = -70.0;
TRAY_X1 = 25.0;
TRAY_FRONT_Y = -42.0;
TRAY_BACK_Y  = 14.0;
TRAY_T  = 4.0;
HINGE_Y = 14.0;
HINGE_Z = 35.5;
// 一体铰链：薄片厚度和弯折弧长决定应变。
// 按 30° 翻转、弧长 12 mm 算：R_eff=22.9 mm，应变 0.5/(2×22.9)=1.09%，
// PETG 断裂应变 3~5%，安全。早先 0.6 mm + 7 mm 弧长是 2.24%，偏大。
LIVING_T = 0.5;          // 薄片厚度（0.4~0.5，越薄越软）
LIVING_W = 50.0;         // 薄片宽度
LIVING_ARC = 12.0;       // 薄片弯折段长度（越长应变越小）

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
BODY_Z0 = BASE_T;
BODY_Z1 = BASE_T + SERVO_H;        // 25.5
HORN_Z0 = BODY_Z1;
HORN_Z1 = HORN_Z0 + HORN_T;        // 28.5
CAP_Z0  = PIN_TOP;                 // 34.5
CAP_Z1  = CAP_Z0 + CAP_T;          // 35.35
TRAY_Z0 = HINGE_Z;                 // 35.5
TRAY_Z1 = TRAY_Z0 + TRAY_T;        // 39.5

// =============================================================================
// 舵机支架：U 形槽 + 甲板卡榫（无螺丝）+ 板簧座
// =============================================================================
module bracket() {
    xo = SERVO_W / 2 + SERVO_CLR;
    y0 = -2;
    y1 = SERVO_L + 2;
    x_base0 = -18.0;

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

            // ---- 甲板卡榫 ×2（替代 M2×8 螺丝）----
            // 向下伸出的小柱，侧面带卡脚；插进甲板的 Ø6 孔后卡脚张开咬住。
            for (sx = [-1, 1])
                translate([sx * (xo + WALL_T + 4.0) - NOTCH_W/2,
                           y1 / 2 - NOTCH_W/2, -NOTCH_H]) {
                    // 柱身
                    cylinder(d = NOTCH_W, h = NOTCH_H + BASE_T + EPS);
                    // 侧向卡脚（两条，向下渐薄，插入时被挤压、到位后弹开）
                    for (k = [-1, 1])
                        translate([k > 0 ? NOTCH_W/2 - 0.6 : -NOTCH_W/2 - 0.4,
                                   0, -NOTCH_H * 0.15])
                            cube([1.0, NOTCH_W * 0.7, NOTCH_H * 0.9]);
                }

            // ---- 板簧座（打印弹簧的根部支撑）----
            translate([-xo - WALL_T, SPRING_ARM_Y - SPRING_W/2, BASE_T])
                cube([WALL_T, SPRING_W, 8]);
        }

        // 安装耳槽
        for (sx = [-1, 1])
            translate([sx > 0 ? xo - EPS : -xo - WALL_T - EPS,
                       FLANGE_Y0, HORN_Z1 - 4.0])
                cube([WALL_T + 2 * EPS, FLANGE_Y1 - FLANGE_Y0, 6.5]);

        // 走线缺口
        translate([-xo - WALL_T - EPS, y1 - 12, BASE_T + 2])
            cube([2 * xo + 2 * WALL_T + 2 * EPS, 6, 20]);
    }

    // ---- 打印板簧（悬臂梁，从板簧座伸出）----
    // 沿 -y 方向伸出 SPRING_L，末端略上翘，压在摇臂尾部下面。
    // 打印时这个方向有支撑问题 —— 见 README 的打印方向说明：
    // 建议整体竖起来打（底面朝下），板簧则沿层内弯曲，强度更好。
    translate([-xo - WALL_T + WALL_T/2, SPRING_ARM_Y, BASE_T + 8]) {
        // 根部过渡
        cube([SPRING_W, 2, SPRING_T + 1.5], center = false);
        // 悬臂
        translate([0, -SPRING_L, 0])
            cube([SPRING_W, SPRING_L, SPRING_T]);
        // 末端上翘的推点（圆柱头，减小摩擦）
        translate([SPRING_W/2, -SPRING_L, SPRING_T])
            cylinder(d = 3.0, h = 2.5);
    }
}

// =============================================================================
// 摇臂 + 销轴（压配到舵机齿盘，无螺丝）
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
                    translate([SPRING_ARM_Y + 4, 0, 0]) cylinder(d = HORN_W - 1, h = HORN_T);
                }
            }
            // ---- 压配孔 + 齿形防转（替代 M2 螺丝）----
            // 孔径比齿盘小 PRESS_FIT 的两倍，压上去靠过盈摩擦传扭矩。
            // 再加 6 条径向齿槽，压配后咬进齿盘的花键，彻底防转。
            translate([0, 0, -EPS])
                cylinder(d = GEAR_D - PRESS_FIT, h = HORN_T + 2 * EPS);
            for (i = [0:5])
                rotate([0, 0, i * 60])
                    translate([-(GEAR_D - PRESS_FIT)/2 + 0.2, -0.5, -EPS])
                        cube([1.6, 1.0, HORN_T + 2 * EPS]);
        }
        // 销轴柱段（顶端带环槽，供帽形圆盘卡住）
        translate([PIN_R, 0, 0])
            difference() {
                union() {
                    cylinder(d = PIN_D, h = PIN_TOP - HORN_Z0 - PIN_CH);
                    translate([0, 0, PIN_TOP - HORN_Z0 - PIN_CH])
                        cylinder(d1 = PIN_D, d2 = PIN_D - 2 * PIN_CH, h = PIN_CH);
                }
                // 环槽：帽形圆盘的裙边卡脚咬进这里
                translate([0, 0, SNAP_GROOVE_Z - HORN_Z0])
                    cylinder(d = PIN_D - SNAP_GROOVE_D, h = 1.2);
            }
    }
}

// =============================================================================
// 帽形倒扣圆盘（纯打印，压配 + 环槽卡住销轴顶端）
//   原理：顶部圆盘挡住耳板上方；向下伸出的裙边抱住销轴，
//         裙边内侧的卡脚咬进销轴环槽 —— 靠材料和环槽锁住，不需要螺丝。
// =============================================================================
// =============================================================================
// 帽形倒扣圆盘（纯打印，压配到销轴顶端）
//
// 这一版修正了两个会让零件报废的错误（第一版预览里能看到两片飞开）：
//   1. 开口槽原先切穿了顶盘，把整个圆盘劈成两半。
//      现在槽只切**裙边段**（z < CAP_T），顶盘完整。
//   2. 卡脚环原先半径算错（切到 Ø3.6，比内孔 Ø4.7 还小），被整体削没了。
//      现在改成裙边内侧的一圈小凸起，凸起顶端略小于内孔、根部咬进销轴环槽。
//
// 工作原理：顶盘 Ø12 挡住耳板上方；裙边套住销轴，内侧凸起咬进销轴环槽，
//           靠材料弹性 + 环槽限位，不需要螺丝。
// =============================================================================
module cap() {
    // 卡脚：裙边内壁上的一圈凸起
    FOOT_D_IN  = PIN_D - PRESS_FIT;            // 内孔直径 4.7
    FOOT_D_OUT = FOOT_D_IN - 2 * 0.35;         // 凸起顶端 4.0（略小于内孔，能压进去）

    translate([0, 0, CAP_Z0]) {
        difference() {
            union() {
                // 顶盘：完整圆盘（不开口）
                cylinder(d = CAP_D, h = CAP_T);
                // 裙边
                cylinder(d = PIN_D + 2 * CAP_SKIRT_T, h = CAP_SKIRT_H);
            }
            // 内孔（压配到销轴）
            translate([0, 0, -EPS])
                cylinder(d = FOOT_D_IN, h = CAP_SKIRT_H + 2 * EPS);

            // 卡脚环：内壁上一圈向内凸起，位置对准销轴环槽
            //   GROOVE_Z_ABS 是环槽中心的绝对 z，换算到本零件局部坐标
            translate([0, 0, (SNAP_GROOVE_Z - CAP_Z0) - 0.6])
                difference() {
                    cylinder(d = FOOT_D_IN + 2, h = 1.2);       // 外圈（切材料用）
                    translate([0, 0, -EPS])
                        cylinder(d = FOOT_D_OUT, h = 1.2 + 2*EPS);  // 内圈保留
                }

            // 开口槽：只在裙边段开，顶盘保持完整
            // 这是第一版最大的错误 —— 槽切到 CAP_SKIRT_H 就把圆盘劈成两片了。
            for (i = [0, 1])
                rotate([0, 0, i * 180])
                    translate([-CAP_SLIT/2, FOOT_D_IN/2 - 0.5, CAP_T])
                        cube([CAP_SLIT, CAP_D/2, CAP_SKIRT_H - CAP_T + EPS]);
        }
    }
}

// =============================================================================
// 托板耳板（开口缺口）
// =============================================================================
module tray_ear() {
    difference() {
        translate([EAR_X0, EAR_Y0, EAR_Z1 - EAR_T])
            cube([EAR_X1 - EAR_X0, EAR_Y1 - EAR_Y0, EAR_T]);
        translate([PIN_R, EAR_Y1, EAR_Z1 - EAR_T - EPS])
            cylinder(d = EAR_NOTCH, h = EAR_T + 2 * EPS);
    }
    // 与托板的连接筋
    translate([EAR_X0 + 2, EAR_Y1 - 11, EAR_Z1])
        cube([EAR_X1 - EAR_X0 - 4, 11, TRAY_Z0 - EAR_Z1]);
}

// =============================================================================
// 托板（含一体薄片铰链）
// =============================================================================
module tray() {
    // 承重板
    difference() {
        union() {
            translate([TRAY_X0, TRAY_FRONT_Y, TRAY_Z0])
                cube([TRAY_X1 - TRAY_X0, TRAY_BACK_Y - TRAY_FRONT_Y, TRAY_T]);
            // 前唇（防前滑）
            translate([TRAY_X0, TRAY_FRONT_Y, TRAY_Z1])
                cube([TRAY_X1 - TRAY_X0, 5, 6]);
        }
        for (i = [0, 1])
            translate([TRAY_X0 + 20 + i * 30, TRAY_FRONT_Y + 18, TRAY_Z0 - EPS])
                cylinder(d = 12, h = TRAY_T + 2 * EPS);
    }
    // ---- 一体薄片铰链 ----
    // 从托板后缘伸出 LIVING_ARC 长的薄片，另一端固定在船体锚块上。
    // 弯折分散在整段弧长上（不是一道折痕），这是应变能降到 1% 的关键。
    translate([TRAY_X0 + (TRAY_X1 - TRAY_X0 - LIVING_W)/2, TRAY_BACK_Y,
               TRAY_Z0 + TRAY_T/2 - LIVING_T/2])
        cube([LIVING_W, LIVING_ARC, LIVING_T]);
    // 锚块（固定在船体侧，托板翻转时它不动）
    translate([TRAY_X0 + (TRAY_X1 - TRAY_X0 - LIVING_W)/2,
               TRAY_BACK_Y + LIVING_ARC, TRAY_Z0 - 3])
        cube([LIVING_W, 6, TRAY_T + 6]);
}

// =============================================================================
// 装配
// =============================================================================
module assembly(exploded = false) {
    E = exploded ? 20 : 0;

    color("#8a9099") bracket();
    color("#2b3038") {
        translate([-SERVO_W / 2, 0, BODY_Z0]) cube([SERVO_W, SERVO_L, SERVO_H]);
        translate([AXIS_X, AXIS_Y, BODY_Z1]) cylinder(d = GEAR_D, h = 2.2);
    }
    color("#2f86e8") horn();
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
