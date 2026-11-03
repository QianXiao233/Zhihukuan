// =============================================================================
// 预览图渲染器（输出到 preview/）
//
// 为什么用"旋转模型"而不是 --camera
//   OpenSCAD 2021.01 无头模式下 --camera 的 7 参数形式常被忽略
//   （实测 4 组不同相机参数渲染出 SHA256 完全相同的 PNG）。
//   所以把模型本身转到目标姿态，用默认相机看，结果确定可控。
//
// 用法：
//   openscad -o out.png --projection=o --imgsize=1400,1050 -D 'VIEW="iso"' render_views.scad
//
// VIEW: iso / front / top / side / locked / released / explode
// =============================================================================
_DM_INCLUDED = true;
include <drop_module.scad>

VIEW = "iso";

SERVO_ANGLE = (VIEW == "released") ? SERVO_TRAVEL_DEG : 0;
TRAY_ANGLE  = (VIEW == "released") ? TRAY_DUMP_DEG : 0;
EXPLODE     = (VIEW == "explode") ? 20 : 0;

// 舵机示意件
module servo_dummy() {
    color("#2b3038") {
        translate([-SERVO_W / 2, 0, BODY_Z0]) cube([SERVO_W, SERVO_L, SERVO_H]);
        translate([AXIS_X, AXIS_Y, BODY_Z1]) cylinder(d = GEAR_D, h = 2.2);
        for (sx = [-SERVO_W / 2 - 4.0, SERVO_W / 2])
            translate([sx, FLANGE_Y0, BODY_Z1 - 9.0])
                cube([4.0, FLANGE_Y1 - FLANGE_Y0, 2.2]);
    }
}

module mechanism() {
    translate([0, 0, -EXPLODE * 1.0]) color("#98a0ab") bracket();
    translate([0, 0, -EXPLODE * 0.4]) servo_dummy();

    // 摇臂：绕竖直舵机轴转
    color("#2f86e8") rotate([0, 0, SERVO_ANGLE]) horn();

    // 倒扣圆盘：跟随摇臂一起转（它是拧在销轴上的）
    color("#7cc0ff") rotate([0, 0, SERVO_ANGLE])
        translate([AXIS_X + PIN_R, AXIS_Y, 0]) cap();

    // 托板/耳板：绕铰链轴（沿 x）翻转
    //   装配主视图里把托板做成**半透明**，否则它整块盖在锁扣上方，
    //   销轴、缺口、圆盘的配合完全看不见（这是实际踩过的坑）。
    translate([0, HINGE_Y, TRAY_Z0 + EXPLODE * 0.7])
        rotate([TRAY_ANGLE, 0, 0])
            translate([0, -HINGE_Y, -TRAY_Z0]) {
                color("#ef9d2e") tray_ear();
                color("#c6cdd8", VIEW == "iso" ? 0.22 : 1.0) tray();
            }
}

module posed() {
    if (VIEW == "top")        mechanism();
    else if (VIEW == "front") rotate([90, 0, 0])  mechanism();
    else if (VIEW == "side")  rotate([90, 0, 90]) mechanism();
    // 装配主视图用俯视偏一点：托板会遮挡侧下方，俯视才能看清
    // 销轴/缺口/圆盘三者的配合，这也是现场装配最需要的视角。
    else                      rotate([24, 0, -14]) mechanism();
}

posed();
