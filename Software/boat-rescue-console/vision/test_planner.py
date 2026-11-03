"""
智护库安 —— 路径规划自测（纯 numpy，无需相机/OpenCV）

运行：
    D:\\miniconda3\\python.exe test_planner.py

覆盖：
  1) A* 不穿膨胀边界（逐点 + 逐段密集采样校验）、路径长度合理、8 邻接禁穿角；
  2) 起终点吸附最近可行格（起点在池外 / 终点在贴壁膨胀区）；
  3) 目标被障碍完全隔断时 reachable=False 且直线兜底；
  4) 覆盖航线：内缩边界内、弓字形方向交替、覆盖率 >= 90%（含闭环版）；
  5) 纯追踪：全路径虚拟目标距离 >= 0.5 m（剩余 > lookahead 时）、剩余短返回终点、
     到达 < 0.08 m 判 arrived；
  6) 状态机：无目标 SEARCH / 有目标 TRACK / 目标移动后重规划 / 最小重规划间隔防抖 /
     覆盖航线走完自动换段（含方向反转）；
  7) 端到端：模拟船沿虚拟目标航行到目标，全程验证 40 cm 交接约束；
  8) 性能：单次 A*、单次覆盖生成、单次 Planner.update 耗时。

设计说明：这是"脚本式断言"测试，不依赖 pytest，任何断言失败会打印 [FAIL] 并以
非 0 退出码结束，方便直接接进 CI 或现场自检。
"""
from __future__ import annotations

import math
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from planner import (                     # noqa: E402
    MODE_SEARCH,
    MODE_TRACK,
    Planner,
    PoolPlanner,
    PurePursuit,
    polyline_length,
)

TOL = 1e-9
RESULTS: list[tuple[str, bool, str]] = []
TESTS: list[tuple[str, object]] = []


# --------------------------------------------------------------------------
# 测试小工具
# --------------------------------------------------------------------------
def resample_polyline(path, step: float = 0.01) -> list[tuple[float, float]]:
    """把折线按弧长等步长重采样（用于"沿整条路径"批量检查）。"""
    pts = np.asarray(path, dtype=float)
    out = [(float(pts[0, 0]), float(pts[0, 1]))]
    for a, b in zip(pts[:-1], pts[1:]):
        seg = b - a
        length = float(np.linalg.norm(seg))
        if length < 1e-12:
            continue
        n = max(1, int(math.ceil(length / step)))
        for k in range(1, n + 1):
            p = a + seg * (k / n)
            out.append((float(p[0]), float(p[1])))
    return out


def assert_free_path(pool: PoolPlanner, path, label: str) -> None:
    """路径上每个点、每条线段的密集采样点都必须在膨胀边界之内。"""
    pts = np.asarray(path, dtype=float)
    assert len(pts) >= 2, f"{label}: 路径点数不足"
    c = pool.clear_total_m
    lo = c - 1e-6
    hi = pool.size_m - c + 1e-6
    for (x, y) in pts:
        assert lo <= x <= hi and lo <= y <= hi, f"{label}: 点 ({x:.4f},{y:.4f}) 越出膨胀边界"
        assert pool.is_free_world(x, y), f"{label}: 点 ({x:.4f},{y:.4f}) 落在障碍内"
    # 线段密集采样：步长 5 mm，远小于船体尺度
    for a, b in zip(pts[:-1], pts[1:]):
        seg = b - a
        length = float(np.linalg.norm(seg))
        n = max(2, int(math.ceil(length / 0.005)) + 1)
        for k in range(n + 1):
            p = a + seg * (k / n)
            assert pool.is_free_world(float(p[0]), float(p[1])), (
                f"{label}: 线段 ({a[0]:.3f},{a[1]:.3f})->({b[0]:.3f},{b[1]:.3f}) "
                f"穿过膨胀边界，采样点 ({p[0]:.4f},{p[1]:.4f})"
            )


def check(name: str):
    """只登记用例，由 main() 统一执行（不在 import 阶段跑）。"""
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def run_test(name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        detail = fn() or ""
        RESULTS.append((name, True, str(detail)))
        print(f"[PASS] {name}  ({time.perf_counter() - t0:.3f}s)  {detail}")
    except AssertionError as exc:
        RESULTS.append((name, False, str(exc)))
        print(f"[FAIL] {name}  ->  {exc}")
    except Exception:                       # noqa: BLE001
        RESULTS.append((name, False, traceback.format_exc()))
        print(f"[ERROR] {name}\n{traceback.format_exc()}")


# --------------------------------------------------------------------------
# 1) A*
# --------------------------------------------------------------------------
@check("A* 空池：不穿膨胀边界 + 长度合理 + 端点吸附")
def test_astar_empty_pool() -> str:
    pool = PoolPlanner()                      # 1.2 m / 0.05 m / 0.09 / 0.05
    assert pool.grid_n == 24
    assert abs(pool.clear_total_m - 0.14) < 1e-12

    start, goal = (0.2, 0.2), (1.0, 1.0)
    path, reachable = pool.plan(start, goal)
    assert reachable is True
    assert_free_path(pool, path, "空池 A*")

    # 起终点吸附到最近可行格中心（不应离请求点太远）
    assert math.hypot(path[0][0] - start[0], path[0][1] - start[1]) <= 0.05
    assert math.hypot(path[-1][0] - goal[0], path[-1][1] - goal[1]) <= 0.05

    length = polyline_length(path)
    straight = math.hypot(path[-1][0] - path[0][0], path[-1][1] - path[0][1])
    assert length >= straight - 1e-9, f"长度 {length:.4f} 小于直线 {straight:.4f}"
    assert length <= 1.25 * straight + 0.02, f"LOS 后长度 {length:.4f} 明显绕远（直线 {straight:.4f}）"
    return f"点数={len(path)} 长度={length:.3f}m 直线={straight:.3f}m"


@check("A* 绕障：不擦碰障碍、比直线长、起点终点仍可达")
def test_astar_with_obstacle() -> str:
    pool = PoolPlanner()
    pool.add_obstacle(0.60, 0.60, 0.10)       # 膨胀后 0.24 m
    start, goal = (0.2, 0.2), (1.0, 1.0)
    path, reachable = pool.plan(start, goal)
    assert reachable is True
    assert_free_path(pool, path, "绕障 A*")

    # 路径点到障碍中心的最小距离必须 >= r + 膨胀
    dmin = min(math.hypot(p[0] - 0.60, p[1] - 0.60) for p in path)
    assert dmin >= 0.10 + pool.clear_total_m - 1e-6, f"贴障碍太近: {dmin:.4f}"

    length = polyline_length(path)
    straight = math.hypot(goal[0] - start[0], goal[1] - start[1])
    assert length > straight, f"绕障长度 {length:.3f} 应大于直线 {straight:.3f}"
    return f"点数={len(path)} 长度={length:.3f}m 直线={straight:.3f}m 距障碍={dmin:.3f}m"


@check("A* 禁穿角：两障碍斜向夹缝不可直接穿过")
def test_astar_corner_rule() -> str:
    pool = PoolPlanner()
    # 对角摆两个障碍，中间留出比船体更窄的斜缝：8 邻接"穿角"会擦到，禁穿角规则必须绕开
    pool.add_obstacle(0.40, 0.40, 0.08)
    pool.add_obstacle(0.50, 0.50, 0.08)
    start, goal = (0.175, 0.575), (0.575, 0.175)   # 绕过障碍群，不得从缝里穿
    path, reachable = pool.plan(start, goal)
    assert_free_path(pool, path, "禁穿角")

    # 逐段检查：每段中点也不能落进任一障碍的膨胀圈
    for a, b in zip(path[:-1], path[1:]):
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        for (ox, oy, r) in pool.obstacles:
            assert math.hypot(mid[0] - ox, mid[1] - oy) >= r + pool.clear_total_m - 1e-6
    assert reachable is True, f"该构型应仍可绕过（reachable={reachable}）"
    return f"可达={reachable} 点数={len(path)} 长度={polyline_length(path):.3f}m"


@check("起终点吸附：池外起点 / 贴壁膨胀区终点")
def test_snap() -> str:
    pool = PoolPlanner()

    # 起点在池外（例如视觉跳点）：应吸附到池内最近可行格
    path, reachable = pool.plan((-0.30, -0.20), (0.60, 0.60))
    assert reachable is True
    assert pool.is_free_world(*path[0])
    snapped = pool.snap(-0.30, -0.20)          # 语义定义：最近可行格中心
    assert path[0] == snapped, f"起点应吸附到 {snapped}，实际 {path[0]}"
    d_start = math.hypot(path[0][0] - (-0.30), path[0][1] - (-0.20))
    assert d_start <= 0.70, f"起点吸附过远: {d_start:.3f}"

    # 终点落在贴壁膨胀区里（0.02 m 处，船心不可能到达）：吸附到最近可行格
    path2, reachable2 = pool.plan((0.60, 0.60), (0.02, 0.60))
    assert reachable2 is True
    assert pool.is_free_world(*path2[-1])
    assert abs(path2[-1][1] - 0.60) < 0.1
    assert abs(path2[-1][0] - pool.clear_total_m) <= 0.06, (
        f"终点应吸附到 x≈{pool.clear_total_m:.2f}，实际 {path2[-1][0]:.3f}")
    assert_free_path(pool, path2, "吸附路径")

    # 起终点在同一格：退化情况也不能崩
    path3, reachable3 = pool.plan((0.6, 0.6), (0.601, 0.601))
    assert reachable3 is True and len(path3) >= 2
    return f"池外起点吸附={d_start:.3f}m 贴壁终点 x={path2[-1][0]:.3f}"


@check("不可达兜底：目标被障碍完全隔断 -> reachable=False + 直线")
def test_unreachable() -> str:
    pool = PoolPlanner()
    # 膨胀半径 0.55 m 的大障碍把内缩方形切成四角孤立口袋
    pool.add_obstacle(0.60, 0.60, 0.41)
    start, goal = (0.175, 0.175), (1.025, 1.025)
    assert pool.is_free_world(*start) and pool.is_free_world(*goal)

    path, reachable = pool.plan(start, goal)
    assert reachable is False, "被完全隔断的目标不应判为可达"
    assert len(path) == 2, f"兜底应给直线（2 点），实际 {len(path)} 点"
    assert path[0] == (start[0], start[1]) and path[-1] == (goal[0], goal[1])

    # Planner 层要把 reachable 透传出来
    planner = Planner(pool_planner=pool)
    out = planner.update((start[0], start[1], 0.0), goal, now=0.0)
    assert out.mode == MODE_TRACK and out.reachable is False
    return f"可达={reachable} 兜底点数={len(path)} 目标直线距离={polyline_length(path):.3f}m"


# --------------------------------------------------------------------------
# 2) 覆盖搜索
# --------------------------------------------------------------------------
@check("覆盖航线：内缩边界内 + 弓字形方向交替 + 覆盖率 >= 90%")
def test_coverage() -> str:
    pool = PoolPlanner()
    lo, hi = pool.coverage_bounds()
    assert abs(lo - 0.14) < 1e-12 and abs(hi - 1.06) < 1e-12

    path = pool.coverage_path()
    assert len(path) >= 4 and len(path) % 2 == 0
    for (x, y) in path:
        assert lo - 1e-9 <= x <= hi + 1e-9, f"航点 x={x} 越界"
        assert lo - 1e-9 <= y <= hi + 1e-9, f"航点 y={y} 越界"
        assert pool.is_free_world(x, y), f"航点 ({x},{y}) 落在障碍内"

    # 弓字形：y 单调不减；每行两点、方向交替、横跨整个内缩宽度
    ys = [p[1] for p in path]
    assert ys == sorted(ys), "航线 y 应单调前进（弓字形）"
    for k in range(0, len(path), 2):
        a, b = path[k], path[k + 1]
        assert abs(a[1] - b[1]) < 1e-9
        assert abs(abs(a[0] - b[0]) - (hi - lo)) < 1e-9
        if (k // 2) % 2 == 0:
            assert abs(a[0] - lo) < 1e-9 and abs(b[0] - hi) < 1e-9
        else:
            assert abs(a[0] - hi) < 1e-9 and abs(b[0] - lo) < 1e-9

    ratio = pool.coverage_ratio(path)
    assert ratio >= 0.90, f"覆盖率 {ratio:.2%} < 90%"

    # 闭环版：首尾同点、覆盖率同样达标、且长度不短于往返版（多了一圈闭环边）
    loop = pool.coverage_path(loop=True)
    assert len(loop) >= len(path)
    assert math.hypot(loop[0][0] - loop[-1][0], loop[0][1] - loop[-1][1]) < 1e-9, "闭环首尾应同点"
    ratio_loop = pool.coverage_ratio(loop)
    assert ratio_loop >= 0.90, f"闭环覆盖率 {ratio_loop:.2%} < 90%"
    for (x, y) in loop:
        assert lo - 1e-9 <= x <= hi + 1e-9 and lo - 1e-9 <= y <= hi + 1e-9

    # 更严格的搜索半宽下覆盖率会下降，说明指标本身是有意义的（不是恒等于 100%）
    ratio_strict = pool.coverage_ratio(path, half_swath_m=0.12)
    assert ratio_strict < ratio, "收紧搜索半宽后覆盖率应下降"

    # 倒圆版（实际给船跑的形态）：仍在界内、覆盖率仍达标、拐角不再是 90° 尖角
    smooth_pingpong = pool.coverage_path(corner_radius_m=0.18)
    smooth_loop = pool.coverage_path(loop=True, corner_radius_m=0.18)
    for sp in (smooth_pingpong, smooth_loop):
        assert len(sp) > len(path), "倒圆后点数应变多"
        for (x, y) in sp:
            assert lo - 1e-9 <= x <= hi + 1e-9 and lo - 1e-9 <= y <= hi + 1e-9, \
                f"倒圆后航点 ({x:.3f},{y:.3f}) 越界"
        assert pool.coverage_ratio(sp) >= 0.90, f"倒圆后覆盖率 {pool.coverage_ratio(sp):.1%}"
    # 倒圆后不该再有 90° 尖角：相邻两段的转角都小于 60°
    for sp in (smooth_pingpong, smooth_loop):
        max_turn = 0.0
        pts = np.asarray(sp, dtype=float)
        for a, b, c in zip(pts[:-2], pts[1:-1], pts[2:]):
            u1 = b - a
            u2 = c - b
            n1 = float(np.linalg.norm(u1))
            n2 = float(np.linalg.norm(u2))
            if n1 < 1e-9 or n2 < 1e-9:
                continue
            cos = max(-1.0, min(1.0, float(u1 @ u2) / (n1 * n2)))
            max_turn = max(max_turn, math.degrees(math.acos(cos)))
        assert max_turn < 60.0, f"倒圆后仍存在 {max_turn:.1f}° 的尖角"

    lane_gap = path[2][1] - path[0][1]
    return (f"行数={len(path)//2} 行距={lane_gap:.3f}m "
            f"覆盖(0.25)={ratio:.1%} 覆盖(0.12)={ratio_strict:.1%} 闭环覆盖={ratio_loop:.1%} "
            f"倒圆后点数={len(smooth_loop)} 尖角<60°")


# --------------------------------------------------------------------------
# 3) 纯追踪
# --------------------------------------------------------------------------
def pursuit_constraint_check(pool: PoolPlanner, path, label: str,
                             lateral: float = 0.0) -> tuple[int, float, int]:
    """
    沿整条路径（可加横向偏移）逐点调用纯追踪，检查 40 cm 交接硬约束。

    :return: (检查帧数, 最小虚拟目标距离, 违规帧数)
    """
    pp = PurePursuit(lookahead_m=0.55)
    pts = [(x, y) for (x, y) in path]
    checked = 0
    worst = float("inf")
    violations = 0
    bad: list[str] = []
    for (x, y) in resample_polyline(pts, step=0.01):
        for dx, dy in ((0.0, 0.0), (lateral, -lateral), (-lateral, lateral)):
            out = pp.compute((x + dx, y + dy, 0.0), pts)
            if out.remaining_m <= pp.lookahead_m + 1e-9:
                continue
            checked += 1
            worst = min(worst, out.distance_m)
            if out.distance_m < 0.5 - 1e-9:
                violations += 1
                if len(bad) < 3:
                    bad.append(f"boat=({x + dx:.3f},{y + dy:.3f}) "
                               f"target=({out.target_x:.3f},{out.target_y:.3f}) "
                               f"dist={out.distance_m:.3f} remaining={out.remaining_m:.3f}")
    assert violations == 0, f"{label}: {violations} 帧虚拟目标距离 < 0.5 m，例如 {bad}"
    return checked, worst, violations


@check("纯追踪：无目标贴脸（直线 / 绕障 A* / 往返覆盖 / 闭环覆盖）")
def test_pure_pursuit_constraint() -> str:
    pool = PoolPlanner()

    # (a) 直线
    straight_path = [(0.175, 0.175), (1.025, 0.175)]
    n1, w1, v1 = pursuit_constraint_check(pool, straight_path, "直线")

    # (b) 带障碍的 A* 路径（真实折线，含拐弯）
    pool2 = PoolPlanner()
    pool2.add_obstacle(0.60, 0.60, 0.10)
    astar_path, ok = pool2.plan((0.175, 0.175), (1.025, 1.025))
    assert ok
    n2, w2, v2 = pursuit_constraint_check(pool2, astar_path, "绕障 A*", lateral=0.03)

    # (c) 往返覆盖航线（4 个 U 形折返）
    cov = pool.coverage_path()
    n3, w3, v3 = pursuit_constraint_check(pool, cov, "往返覆盖", lateral=0.03)

    # (d) 闭环覆盖航线（最短闭合边已旋转到最长段，末端不会折返贴脸）
    loop = pool.coverage_path(loop=True)
    n4, w4, v4 = pursuit_constraint_check(pool, loop, "闭环覆盖", lateral=0.03)

    worst = min(w1, w2, w3, w4)
    return (f"检查 {n1 + n2 + n3 + n4} 帧 / 违规 {v1 + v2 + v3 + v4}，"
            f"最小虚拟目标距离={worst:.4f}m（要求 >= 0.5000）")


@check("纯追踪：剩余短返回终点 + 到达 < 0.08 m 判 arrived")
def test_pure_pursuit_terminal() -> str:
    pp = PurePursuit(lookahead_m=0.55)
    path = [(0.2, 0.2), (1.0, 0.2)]           # 0.8 m 直线

    # 剩余 0.30 m < lookahead：直接给终点
    out = pp.compute((0.7, 0.2, 90.0), path)
    assert abs(out.remaining_m - 0.30) < 1e-9, f"remaining={out.remaining_m}"
    assert (abs(out.target_x - 1.0) < 1e-9 and abs(out.target_y - 0.2) < 1e-9), \
        f"剩余短时应返回终点，实际 ({out.target_x:.3f},{out.target_y:.3f})"
    assert out.arrived is False

    # 剩余 0.55 m 恰好等于 lookahead 的边界：也应给终点
    out = pp.compute((0.45, 0.2, 90.0), path)
    assert abs(out.remaining_m - 0.55) < 1e-9
    assert abs(out.target_x - 1.0) < 1e-9

    # 剩余 > lookahead：给前方 lookahead 处而非终点
    out = pp.compute((0.2, 0.2, 90.0), path)
    assert out.remaining_m > 0.55
    assert abs(out.target_x - 0.75) < 1e-9 and abs(out.target_y - 0.2) < 1e-9, \
        f"lookahead 点应为 (0.75,0.2)，实际 ({out.target_x:.3f},{out.target_y:.3f})"
    assert out.distance_m >= 0.5

    # 到达判定（阈值 0.08 m）
    assert pp.compute((0.91, 0.2, 90.0), path).arrived is False    # 距终点 0.09 m
    assert pp.compute((0.93, 0.2, 90.0), path).arrived is True     # 距终点 0.07 m < 0.08
    assert pp.compute((0.95, 0.2, 90.0), path).arrived is True     # 0.05 m
    assert pp.compute((1.02, 0.2, 90.0), path).arrived is True     # 冲过头也算到

    # 单点路径退化输入
    out = pp.compute((0.5, 0.5, 0.0), [(0.5, 0.52)])
    assert abs(out.target_x - 0.5) < 1e-9 and out.remaining_m < 0.021
    return (f"remaining=0.30->终点; remaining=0.55->终点; "
            f"lookahead点(0.750,0.200) 距离={0.55:.2f}; arrived 阈值 0.08 正常")


# --------------------------------------------------------------------------
# 4) 状态机
# --------------------------------------------------------------------------
@check("状态机：SEARCH/TRACK 切换 + 最小重规划间隔 + 定期重规划")
def test_state_machine() -> str:
    planner = Planner(replan_interval_s=1.0, min_replan_interval_s=0.2,
                      target_move_threshold_m=0.15)
    boat = (0.175, 0.175, 0.0)

    # 首次：无目标 -> SEARCH
    o1 = planner.update(boat, None, now=0.0)
    assert o1.mode == MODE_SEARCH and o1.reachable is True
    assert o1.path and len(o1.path) >= 4
    assert planner.replan_count == 1
    # SEARCH 输出的虚拟目标不应贴脸（船端 40 cm 就切末端，搜索段会卡住）
    d1 = math.hypot(o1.target_x - boat[0], o1.target_y - boat[1])
    assert d1 >= 0.5 - 1e-9, f"SEARCH 首帧虚拟目标贴脸: {d1:.3f}"

    # 出现目标 -> 立刻切 TRACK
    o2 = planner.update(boat, (0.95, 0.95), now=2.0)
    assert o2.mode == MODE_TRACK
    assert planner.replan_count == 2
    assert abs(o2.path[-1][0] - 0.95) < 0.06 and abs(o2.path[-1][1] - 0.95) < 0.06

    # 目标小抖动（< 0.15 m 阈值）：不应重规划
    n = planner.replan_count
    planner.update(boat, (0.97, 0.96), now=2.05)
    assert planner.replan_count == n, "目标小抖动不应触发重规划"

    # 目标跳变但距上次重规划只有 0.05 s < 0.2 s：防抖，暂不重规划
    planner.update(boat, (0.95, 0.15), now=2.10)
    assert planner.replan_count == n, "最小重规划间隔内不应重规划"

    # 过了最小间隔：立刻重规划到新目标
    o3 = planner.update(boat, (0.95, 0.15), now=2.40)
    assert planner.replan_count == n + 1, "超过最小间隔后应重规划"
    assert abs(o3.path[-1][1] - 0.15) < 0.06, f"重规划后终点 y={o3.path[-1][1]:.3f}"

    # 目标静止：定期重规划（1.0 s）
    n = planner.replan_count
    planner.update(boat, (0.95, 0.15), now=3.0)
    assert planner.replan_count == n, "未到定期重规划周期不应重规划"
    planner.update(boat, (0.95, 0.15), now=3.5)
    assert planner.replan_count == n + 1, "到定期周期应重规划"

    # 目标消失 -> 回到 SEARCH
    o4 = planner.update(boat, None, now=5.0)
    assert o4.mode == MODE_SEARCH and planner.replan_count == n + 2

    # 鸭子类型兼容：直接喂 boat.BoatPose 这种带 .x/.y/.heading 的对象（不 import cv2）
    class _Pose:                       # 与 boat.BoatPose 同形的轻量替身
        x, y, heading = 0.175, 0.175, 12.5

    o5 = planner.update(_Pose(), None, now=8.0)
    assert o5.mode == MODE_SEARCH
    return (f"replan_count={planner.replan_count} "
            f"SEARCH首帧距离={d1:.3f}m 模式={o1.mode}->{o2.mode}->{o4.mode} "
            f"BoatPose兼容={o5.mode}")


def simulate_boat(planner: Planner, start_xy, heading_deg: float, target_or_none,
                  steps: int, dt: float = 0.05, speed: float = 0.22,
                  turn_rate_deg: float = 140.0,
                  stop_on_arrival: bool = False) -> list[dict]:
    """
    单轮车（差速船）运动学仿真：只接受前向速度、转向限速，边转边走。

    和船端一致：航向 0°=+Y、顺时针为正，PID 朝下发目标转。
    用单轮车而不是"直接朝目标平移"（全向轮），是因为全向轮能瞬间对准，会高估船的
    机动性，把真实的"跟线滞后"掩盖掉。
    """
    x, y = float(start_xy[0]), float(start_xy[1])
    h = math.radians(float(heading_deg))
    frames: list[dict] = []
    for k in range(steps):
        out = planner.update((x, y, math.degrees(h) % 360.0), target_or_none, now=k * dt)
        dx, dy = out.target_x - x, out.target_y - y
        d = math.hypot(dx, dy)
        frames.append({"k": k, "boat": (x, y), "out": out, "dist": d,
                       "pursuit": planner.last_pursuit, "replan": planner.replan_count})
        if stop_on_arrival and out.arrived and d < 0.05:
            break
        desired = math.atan2(dx, dy)                       # 与 locator.py 同一航向约定
        err = (desired - h + math.pi) % (2.0 * math.pi) - math.pi
        max_turn = math.radians(turn_rate_deg) * dt
        h += max(-max_turn, min(max_turn, err))
        v = speed * dt * max(0.0, math.cos(err)) ** 0.5    # 边转边走（船一直有推力）
        x += v * math.sin(h)
        y += v * math.cos(h)
    return frames


def assert_in_bounds(pool: PoolPlanner, frames, label: str = "") -> None:
    lo, hi = pool.coverage_bounds()
    for f in frames:
        assert lo - 1e-6 <= f["boat"][0] <= hi + 1e-6, f"{label}第 {f['k']} 帧 x 越界"
        assert lo - 1e-6 <= f["boat"][1] <= hi + 1e-6, f"{label}第 {f['k']} 帧 y 越界"


@check("状态机·SEARCH 巡逻：全程虚拟目标 >= 0.5 m（不会误切二哈末端）")
def test_search_patrol() -> str:
    planner = Planner()                      # 默认：往返 + 标准弓字形
    frames = simulate_boat(planner, (0.20, 0.20), 0.0, None, steps=600)

    min_dist = float("inf")
    min_dist_active = float("inf")       # 只看"剩余 > lookahead"的帧（硬约束适用区间）
    violations = 0
    held = 0
    terminal = 0
    for f in frames:
        out, p = f["out"], f["pursuit"]
        assert out.mode == MODE_SEARCH
        assert out.reachable is True
        min_dist = min(min_dist, f["dist"])
        if p is not None and p.held:
            held += 1
        if out.remaining_m > planner.pursuit.lookahead_m + 1e-9:
            min_dist_active = min(min_dist_active, f["dist"])
            if f["dist"] < 0.5 - 1e-9:
                violations += 1
        else:
            terminal += 1
    assert violations == 0, (
        f"SEARCH 有 {violations} 帧虚拟目标 < 0.5 m（船端会当成末端目标提前切换）")
    assert min_dist_active >= 0.5 - 1e-9, f"最小虚拟目标距离 {min_dist_active:.4f} m"
    assert_in_bounds(planner.pool, frames, "SEARCH ")

    xs = [f["boat"][0] for f in frames]
    travel = sum(math.hypot(frames[i]["boat"][0] - frames[i - 1]["boat"][0],
                            frames[i]["boat"][1] - frames[i - 1]["boat"][1])
                 for i in range(1, len(frames)))
    assert travel > 2.0, f"巡逻里程过短 {travel:.2f} m"
    assert max(xs) - min(xs) > 0.3, f"左右扫幅过小 {max(xs) - min(xs):.2f} m"

    # 航线几何覆盖率 >= 90%；船的实际扫掠轨迹受 0.5 m 操纵粒度限制，只作参考打印
    route_cover = planner.pool.coverage_ratio(frames[-1]["out"].path)
    assert route_cover >= 0.90, f"覆盖航线覆盖率 {route_cover:.1%}"
    swept = planner.pool.coverage_ratio_multi(
        [[(f["boat"][0], f["boat"][1]) for f in frames]])
    assert swept >= 0.50, f"实际扫掠覆盖 {swept:.1%} 过低（船没动起来？）"
    return (f"{len(frames)} 帧（{len(frames) * 0.05:.1f}s 仿真）"
            f"最小虚拟目标距离={min_dist_active:.4f}m（末端区 {terminal} 帧另计，"
            f"全程最小 {min_dist:.3f}m）兜底={held} 次 里程≈{travel:.2f}m "
            f"航线覆盖={route_cover:.1%} 实扫≈{swept:.1%} 换段={planner.replan_count} 次")


@check("状态机·SEARCH 往返换段：到航点末端自动反转，新起点贴着船")
def test_search_reverse() -> str:
    planner = Planner()
    cov = planner.pool.coverage_path()       # 标准弓字形（首尾 = 两一行的端点）
    end = cov[-1]
    frames = simulate_boat(planner, end, 180.0, None, steps=80)

    arrived = [f for f in frames if f["out"].arrived]
    assert arrived, "船在航线末端应判 arrived（提前换段，不贴到 40 cm 以内）"
    f0 = arrived[0]

    later = [f for f in frames if f["k"] > f0["k"]]
    assert later, "arrived 之后仿真帧不足"
    assert later[0]["replan"] > f0["replan"], "arrived 后应重规划换段"
    p0 = later[0]["out"].path[0]
    d0 = math.hypot(p0[0] - later[0]["boat"][0], p0[1] - later[0]["boat"][1])
    assert d0 <= 0.35, f"反转后航线起点距船 {d0:.3f} m（应贴船，否则要白跑回去）"
    assert later[0]["dist"] >= 0.5 - 1e-9, (
        f"换段后虚拟目标仅 {later[0]['dist']:.3f} m（应回到 >=0.5 m 的坐标导航）")
    return (f"{len(frames)} 帧内到点 {len(arrived)} 次，换段后起点距船={d0:.3f}m，"
            f"新虚拟目标={later[0]['dist']:.3f}m")


@check("端到端 TRACK：真船模型下开到目标，全程满足 40 cm 交接约束")
def test_track_end_to_end() -> str:
    pool = PoolPlanner()
    pool.add_obstacle(0.60, 0.60, 0.10)
    planner = Planner(pool_planner=pool)
    goal = (1.025, 1.025)
    frames = simulate_boat(planner, (0.175, 0.175), 0.0, goal, steps=900,
                           stop_on_arrival=True)

    terminal = 0
    min_terminal = float("inf")
    for f in frames:
        out = f["out"]
        assert out.mode == MODE_TRACK
        assert out.reachable is True
        if out.remaining_m > planner.pursuit.lookahead_m + 1e-9:
            assert f["dist"] >= 0.5 - 1e-9, (
                f"第 {f['k']} 帧 remaining={out.remaining_m:.3f} 但虚拟目标 {f['dist']:.3f}")
        if f["dist"] < 0.4:                  # 船端 40 cm 末端切换点
            terminal += 1
            min_terminal = min(min_terminal, f["dist"])
            assert out.remaining_m <= planner.pursuit.lookahead_m + 1e-6, (
                "出现「虚拟目标 < 0.4 m 但路径剩余仍 > lookahead」的提前切换")

    last = frames[-1]
    final = math.hypot(goal[0] - last["boat"][0], goal[1] - last["boat"][1])
    assert final < 0.12, f"未收敛到目标，最终距离 {final:.3f} m"
    assert terminal >= 1, "末端应至少出现一次 40 cm 内的虚拟目标（交接生效）"
    return (f"{len(frames)} 帧（{len(frames) * 0.05:.1f}s）收敛，终点误差={final:.4f}m，"
            f"末端区 {terminal} 帧（最近 {min_terminal:.3f}m），"
            f"最慢单次规划 {planner.last_plan_ms:.2f}ms")


# --------------------------------------------------------------------------
# 6) 性能
# --------------------------------------------------------------------------
@check("性能：单次规划耗时（A* / 覆盖 / Planner.update）")
def test_performance() -> str:
    pool = PoolPlanner()
    n_iter = 200

    t0 = time.perf_counter()
    for _ in range(n_iter):
        pool.plan((0.175, 0.175), (1.025, 1.025))
    empty_ms = (time.perf_counter() - t0) / n_iter * 1000.0

    pool2 = PoolPlanner()
    pool2.add_obstacle(0.60, 0.60, 0.10)
    t0 = time.perf_counter()
    for _ in range(n_iter):
        pool2.plan((0.175, 0.175), (1.025, 1.025))
    obst_ms = (time.perf_counter() - t0) / n_iter * 1000.0

    t0 = time.perf_counter()
    for _ in range(n_iter):
        pool.coverage_path(loop=False)
    cov_ms = (time.perf_counter() - t0) / n_iter * 1000.0

    # Planner.update 稳态（不触发重规划）
    planner = Planner()
    planner.update((0.175, 0.175, 0.0), (1.025, 1.025), now=0.0)
    t0 = time.perf_counter()
    for i in range(n_iter):
        planner.update((0.175, 0.175, 0.0), (1.025, 1.025), now=0.30 + i * 0.001)
    update_ms = (time.perf_counter() - t0) / n_iter * 1000.0

    # 最坏情况：每帧都重规划（目标每帧跳变、间隔放大到 >= min 间隔）
    planner2 = Planner()
    t0 = time.perf_counter()
    for i in range(n_iter):
        planner2.update((0.175, 0.175, 0.0), (0.6 + 0.4 * ((i % 2) * 2 - 1) * 0.5, 0.6),
                        now=i * 0.25)
    replan_ms = (time.perf_counter() - t0) / n_iter * 1000.0

    budget = 1000.0 / 20.0
    assert empty_ms < budget, f"A* 单次 {empty_ms:.2f} ms 超出 20 Hz 帧预算 {budget:.0f} ms"
    assert replan_ms < budget, f"重规划帧 {replan_ms:.2f} ms 超出 20 Hz 帧预算"
    return (f"A*(空池)={empty_ms:.3f}ms A*(绕障)={obst_ms:.3f}ms "
            f"覆盖生成={cov_ms:.3f}ms update(稳态)={update_ms:.3f}ms "
            f"update(每帧重规划)={replan_ms:.3f}ms  [20Hz 预算={budget:.0f}ms]")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main() -> int:
    print("=" * 78)
    print("智护库安 · 路径规划自测 (vision/planner.py)")
    print("=" * 78)
    for name, fn in TESTS:
        run_test(name, fn)

    print("-" * 78)
    passed = sum(1 for _n, ok, _d in RESULTS if ok)
    failed = len(RESULTS) - passed
    for name, ok, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print("-" * 78)
    print(f"总计 {len(RESULTS)} 项：通过 {passed}，失败 {failed}")
    if failed:
        print("\n失败详情：")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  [{name}]\n{detail}\n")
        return 1
    print("全部通过 [OK]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
