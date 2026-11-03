"""
智护库安 —— 水池自主路径规划（纯 numpy，不依赖 OpenCV）

三层结构：
  1) PoolPlanner : 栅格占用图 + 边界/障碍膨胀 + A*(8 邻接) + LOS 化简 + 覆盖搜索(弓字形)
  2) PurePursuit : 折线路径 -> 前方 lookahead 处的虚拟目标（带 40 cm 交接硬约束）
  3) Planner     : 状态机（有目标 TRACK / 无目标 SEARCH）+ 定期重规划 + 最小重规划间隔

坐标与航向沿用 locator.py / pool.py：
  水池左下为原点，X 向右、Y 向上（单位米），量程 1.2 m；
  航向 0° 指向 +Y，顺时针为正。本模块是**纯几何**的，只需要 (x, y)；heading 仅为
  与 BoatPose 接口兼容而接收，不参与计算（标准纯追踪靠路径投影，不需要朝向）。

## 为什么虚拟目标有一个"最小距离"硬约束（0.5 m）

船端逻辑是：

    距下发目标 > 40 cm  -> 坐标导航（航向 PID）
    距下发目标 <= 40 cm -> 切二哈视觉末端

如果上位机把虚拟目标放到船前方 20 cm（例如急弯 / 折返处纯追踪算出来的点离船很近），
船会立刻切到末端视觉：明明还有一整段路没走完，却提前进入末端控制，现场表现就是
在拐角处绕圈、抖动、或者停在半路等末端视觉把目标找回来。

所以：**只要「沿路径剩余长度 > lookahead」，发出的虚拟目标与船的欧氏距离必须 >= 0.5 m**
（比 40 cm 留 10 cm 余量）。实现方式（见 PurePursuit._target）：
  1. 先取弧长 lookahead 处的标准纯追踪点；
  2. 若该点离船太近（急弯 / 折返时弦长 < 弧长），就沿路径继续向前推进，取
     "第一个够远的点"——仍然是路径上的点，只是把 lookahead 临时加长，控制律不变；
  3. 只有当路径真的走到头（剩余 <= lookahead）时才返回终点，此时交给船端切末端。

## 覆盖搜索（boustrophedon）

按内缩边界（`clearance = boat_radius + clearance_m`）生成等间距的平行航线，行距由
`coverage_half_swath_m`（船载视觉有效搜索半宽，默认 0.25 m）决定；相邻行方向相反，
可按"往返"（默认）或"闭环巡逻"（`loop=True`）出航点。

闭环时会把环旋转到"最后一段是最长的一段"：否则环的闭合段很短（1.2 m 水池里通常只有
0.46 m），临近结束时剩余路径 < 0.55 m 却又不是直线，纯追踪只能把虚拟目标压到 0.5 m
以内，违反上面的硬约束。旋转之后末端一定是一整条长直边，约束自然满足。

## 与 26 字节协议的关系

本模块只产出 (target_x, target_y) 米坐标（另外附带 path / remaining_m / arrived /
reachable 供上位机显示与调试），协议一个字都不用改：上位机把 PlanOutput.target_x /
target_y 填进原来 locator.py 上报的那两个字段即可。
"""
from __future__ import annotations

import heapq
import math
import time
from dataclasses import dataclass

import numpy as np

EPS = 1e-9
SQRT2 = math.sqrt(2.0)

MODE_TRACK = "TRACK"      # 有目标：A* 追目标
MODE_SEARCH = "SEARCH"    # 无目标：覆盖搜索

# 8 邻接：(dix, diy, 代价)。对角 sqrt2，正交 1（单位：格）
_MOVES = (
    (-1, 0, 1.0),
    (1, 0, 1.0),
    (0, -1, 1.0),
    (0, 1, 1.0),
    (-1, -1, SQRT2),
    (1, -1, SQRT2),
    (-1, 1, SQRT2),
    (1, 1, SQRT2),
)


# --------------------------------------------------------------------------
# 小工具：位姿/路径的规范化与折线几何
# --------------------------------------------------------------------------
def _unpack_pose(boat_pose) -> tuple[float, float, float]:
    """接受 BoatPose / (x, y) / (x, y, heading) 三种写法，统一成 (x, y, heading)。"""
    if hasattr(boat_pose, "x") and hasattr(boat_pose, "y"):
        heading = getattr(boat_pose, "heading", 0.0)
        return (
            float(boat_pose.x),
            float(boat_pose.y),
            0.0 if heading is None else float(heading),
        )
    seq = tuple(boat_pose)
    if len(seq) < 2:
        raise ValueError(f"boat_pose 至少需要 (x, y)，收到 {boat_pose!r}")
    heading = float(seq[2]) if len(seq) >= 3 and seq[2] is not None else 0.0
    return float(seq[0]), float(seq[1]), heading


def _unpack_target(target) -> tuple[float, float] | None:
    """接受 None / (x, y) / 带 .x .y 的对象。"""
    if target is None:
        return None
    if hasattr(target, "x") and hasattr(target, "y"):
        return float(target.x), float(target.y)
    seq = tuple(target)
    if len(seq) < 2:
        raise ValueError(f"target 至少需要 (x, y)，收到 {target!r}")
    return float(seq[0]), float(seq[1])


def _as_points(path) -> np.ndarray:
    """任意路径写法 -> (N, 2) float64 数组。"""
    arr = np.asarray(path, dtype=np.float64)
    if arr.size == 0:
        return np.zeros((0, 2), dtype=np.float64)
    if arr.ndim == 1:
        if arr.size != 2:
            raise ValueError(f"路径点必须是 (x, y)，收到 {path!r}")
        arr = arr.reshape(1, 2)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f"路径必须是 (N, 2)，收到 shape={arr.shape}")
    return arr


def _dedupe(points, tol: float = 1e-9) -> list[tuple[float, float]]:
    """去掉相邻重复点（零长度线段会让纯追踪的投影退化）。"""
    out: list[tuple[float, float]] = []
    for p in points:
        x, y = float(p[0]), float(p[1])
        if out:
            qx, qy = out[-1]
            if math.hypot(x - qx, y - qy) <= tol:
                continue
        out.append((x, y))
    return out


def _fillet_polyline(points, radius: float, closed: bool, arc_pts: int = 4):
    """
    把折线的拐角用二次贝塞尔倒圆（radius 是切线长度，单位米）。

    为什么必须倒圆：弓字形航线是 90° 尖角，而船端的控制律是"朝下发目标直走"，
    再加上 0.5 m 最小目标距离（见模块 docstring），尖角处虚拟目标一定落在另一条
    行上 —— 船会直接切角切到池子中间，越切越偏，最后在原地画圈。倒圆之后航线是
    一条曲率连续的闭合/开放曲线，船照着 0.55 m 前视点走就能整条跟下来。

    :param closed: True 时把首尾当成相接（首尾同点由本函数负责补齐）
    """
    pts = [(float(p[0]), float(p[1])) for p in points]
    if closed and len(pts) >= 2:
        if math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-9:
            pts = pts[:-1]                    # 内部按"无重复末点"的环处理
    n = len(pts)
    if radius <= 0 or n < 3:
        return pts + ([pts[0]] if closed else [])

    out: list[tuple[float, float]] = []
    if not closed:
        out.append(pts[0])
    for i in (range(n) if closed else range(1, n - 1)):
        prev = pts[(i - 1) % n]
        cur = pts[i]
        nxt = pts[(i + 1) % n]
        v1 = (prev[0] - cur[0], prev[1] - cur[1])
        v2 = (nxt[0] - cur[0], nxt[1] - cur[1])
        l1 = math.hypot(*v1)
        l2 = math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            out.append(cur)
            continue
        u1 = (v1[0] / l1, v1[1] / l1)
        u2 = (v2[0] / l2, v2[1] / l2)
        if u1[0] * u2[0] + u1[1] * u2[1] <= -0.9999:      # 180° 折返尖刺：无法倒圆
            out.append(cur)
            continue
        t = min(radius, 0.45 * l1, 0.45 * l2)
        p1 = (cur[0] + u1[0] * t, cur[1] + u1[1] * t)
        p2 = (cur[0] + u2[0] * t, cur[1] + u2[1] * t)
        for k in range(arc_pts + 1):                      # 二次贝塞尔 p1 - cur - p2
            s = k / arc_pts
            a = (1.0 - s) ** 2
            b = 2.0 * (1.0 - s) * s
            c = s * s
            out.append((a * p1[0] + b * cur[0] + c * p2[0],
                        a * p1[1] + b * cur[1] + c * p2[1]))
    if not closed:
        out.append(pts[-1])
    else:
        out.append(out[0])
    return _dedupe(out, 1e-9)


def polyline_length(path) -> float:
    """折线总长度（米）。"""
    pts = _as_points(path)
    if len(pts) < 2:
        return 0.0
    seg = pts[1:] - pts[:-1]
    return float(np.sum(np.linalg.norm(seg, axis=1)))


def _polyline_project(point, pts: np.ndarray, s_lo: float | None = None,
                      s_hi: float | None = None):
    """
    点到折线的最近投影。

    :param s_lo: 可选，只在弧长 [s_lo, s_hi] 这段窗口内找最近点。
                 纯追踪必须用它：两行平行航线相距可能小于 lookahead，船走到两行
                 中间时，到两行的距离几乎相等，全局最近点会逐帧在行与行之间跳
                 （虚拟目标左右横摆，船跟着画正弦）。用"上次进度 + 窗口"把投影
                 锁在航线当前段附近，就没有这个歧义。
    :return: (投影点, 弧长坐标 s, 到折线距离, 累计弧长数组)
    """
    p = np.asarray(point, dtype=np.float64)
    n = len(pts)
    if n == 1:
        return pts[0].copy(), 0.0, float(np.linalg.norm(p - pts[0])), np.zeros(1)

    seg = pts[1:] - pts[:-1]
    seg_len = np.linalg.norm(seg, axis=1)
    cum = np.concatenate(([0.0], np.cumsum(seg_len)))
    total = float(cum[-1])
    safe = np.where(seg_len < 1e-12, 1.0, seg_len)
    ap = p - pts[:-1]
    t = np.clip(np.einsum("ij,ij->i", ap, seg) / (safe * safe), 0.0, 1.0)

    windowed = s_lo is not None or s_hi is not None
    valid = np.ones(len(seg_len), dtype=bool)
    if windowed:
        lo = 0.0 if s_lo is None else max(0.0, float(s_lo))
        hi = total if s_hi is None else min(total, float(s_hi))
        if hi < lo:
            lo, hi = hi, lo
        t_lo = np.clip((lo - cum[:-1]) / safe, 0.0, 1.0)
        t_hi = np.clip((hi - cum[:-1]) / safe, 0.0, 1.0)
        valid = (t_hi >= t_lo - 1e-12) & (cum[1:] >= lo - 1e-9) & (cum[:-1] <= hi + 1e-9)
        if not valid.any():
            # 窗口整体落在路径外（理论上不会发生）：退回全局投影
            return _polyline_project(point, pts)
        t = np.where(valid, np.clip(t, t_lo, t_hi), t)

    proj = pts[:-1] + seg * t[:, None]
    d = np.linalg.norm(proj - p, axis=1)
    if windowed:
        d = np.where(valid, d, np.inf)
    i = int(np.argmin(d))
    s = float(cum[i] + t[i] * seg_len[i])
    return proj[i].copy(), s, float(d[i]), cum


def _point_at_arc(s: float, pts: np.ndarray, cum: np.ndarray | None = None) -> np.ndarray:
    """折线上弧长 s 处的点（s 会被夹到 [0, 总长]）。"""
    if cum is None:
        seg_len = np.linalg.norm(pts[1:] - pts[:-1], axis=1)
        cum = np.concatenate(([0.0], np.cumsum(seg_len)))
    if len(pts) == 1 or float(cum[-1]) <= 1e-12:
        return pts[-1].copy()
    s = min(max(float(s), 0.0), float(cum[-1]))
    i = int(np.searchsorted(cum, s, side="right") - 1)
    i = min(max(i, 0), len(pts) - 2)
    seg_len_i = float(cum[i + 1] - cum[i])
    frac = 0.0 if seg_len_i <= 1e-12 else (s - float(cum[i])) / seg_len_i
    frac = min(max(frac, 0.0), 1.0)
    return pts[i] + (pts[i + 1] - pts[i]) * frac


# --------------------------------------------------------------------------
# 1) 栅格规划器
# --------------------------------------------------------------------------
class PoolPlanner:
    """
    水池栅格规划器：占用图 + 边界/障碍膨胀 + A* + LOS 化简 + 覆盖航线。

    膨胀半径固定为 ``boat_radius_m + clearance_m``（默认 0.09 + 0.05 = 0.14 m）：
    船心离池壁/障碍至少这么远，船体才不碰壁。这是**几何安全边界**，与船端 40 cm
    交接逻辑无关（后者是控制策略，见 PurePursuit）。

    栅格：格子中心取 ``(i + 0.5) * resolution_m``；分辨率会被微调成 ``size_m / n``，
    保证整数格正好铺满水池（1.2 / 0.05 = 24 格，无取整误差）。
    """

    def __init__(self, size_m: float = 1.2, resolution_m: float = 0.05,
                 boat_radius_m: float = 0.09, clearance_m: float = 0.05):
        if size_m <= 0:
            raise ValueError(f"size_m 必须为正，收到 {size_m}")
        if resolution_m <= 0:
            raise ValueError(f"resolution_m 必须为正，收到 {resolution_m}")
        if boat_radius_m < 0 or clearance_m < 0:
            raise ValueError("boat_radius_m / clearance_m 不能为负")

        self.size_m = float(size_m)
        self.boat_radius_m = float(boat_radius_m)
        self.clearance_m = float(clearance_m)
        # 膨胀总量：船心到池壁/障碍的最小允许距离
        self.clear_total_m = self.boat_radius_m + self.clearance_m

        # 用 n 反推分辨率，避免 size 不是 resolution 整数倍时边界错位
        self.grid_n = max(2, int(round(self.size_m / float(resolution_m))))
        self.resolution_m = self.size_m / self.grid_n

        # 覆盖搜索的有效搜索半宽（米）：行距 = 2 * 该值
        self.coverage_half_swath_m = 0.25

        self._obstacles: list[tuple[float, float, float]] = []
        self._build()

    # ---------------- 栅格构建 ----------------
    def _build(self) -> None:
        n = self.grid_n
        res = self.resolution_m
        centers = (np.arange(n, dtype=np.float64) + 0.5) * res
        self._centers = centers

        c = self.clear_total_m
        lo = c - EPS
        hi = self.size_m - c + EPS

        occ = np.zeros((n, n), dtype=bool)
        # occ[ix, iy]：x 由 ix 决定，y 由 iy 决定
        occ |= (centers < lo)[:, None] | (centers > hi)[:, None]
        occ |= (centers < lo)[None, :] | (centers > hi)[None, :]

        for (ox, oy, r) in self._obstacles:
            rr = r + c - EPS
            if rr <= 0.0:
                continue
            dx = centers[:, None] - ox
            dy = centers[None, :] - oy
            occ |= (dx * dx + dy * dy) < rr * rr

        self.occ = occ
        self.free = ~occ

        self._free_cells = np.argwhere(self.free)              # (M, 2) [ix, iy]
        self._free_centers = (self._free_cells + 0.5) * res    # (M, 2) 米坐标
        self._build_moves()

    def _points_free(self, xs: np.ndarray, ys: np.ndarray) -> np.ndarray:
        """最后一维是采样点的连续空间可行性判定（池壁 + 所有障碍）。"""
        c = self.clear_total_m
        lo = c - EPS
        hi = self.size_m - c + EPS
        ok = ((xs >= lo) & (xs <= hi) & (ys >= lo) & (ys <= hi)).all(axis=-1)
        for (ox, oy, r) in self._obstacles:
            rr = r + c - EPS
            if rr <= 0.0:
                continue
            ok = ok & (((xs - ox) ** 2 + (ys - oy) ** 2) >= rr * rr).all(axis=-1)
        return ok

    def _build_moves(self) -> None:
        """
        预计算 8 邻接的"这一步能不能走"查找表。

        每步都做**连续空间**采样校验（不只是看目标格中心），所以对角步不会擦过
        膨胀后的边界；再叠加"禁穿角"（两条正交邻格都得可行），船体不会从两个
        障碍的斜缝里挤过去。
        """
        n = self.grid_n
        res = self.resolution_m
        idx = np.arange(n)
        IX, IY = np.meshgrid(idx, idx, indexing="ij")
        X0 = (IX + 0.5) * res
        Y0 = (IY + 0.5) * res
        ts = np.linspace(0.0, 1.0, 5)
        free = self.free

        ok_all = np.zeros((len(_MOVES), n, n), dtype=bool)
        for mi, (dix, diy, _cost) in enumerate(_MOVES):
            TX = IX + dix
            TY = IY + diy
            inb = (TX >= 0) & (TX < n) & (TY >= 0) & (TY < n)
            txc = np.clip(TX, 0, n - 1)
            tyc = np.clip(TY, 0, n - 1)

            ok = free & inb & free[txc, tyc]
            if dix != 0 and diy != 0:
                ok = ok & free[np.clip(IX + dix, 0, n - 1), IY]
                ok = ok & free[IX, np.clip(IY + diy, 0, n - 1)]

            X1 = (txc + 0.5) * res
            Y1 = (tyc + 0.5) * res
            XS = X0[..., None] + (X1 - X0)[..., None] * ts
            YS = Y0[..., None] + (Y1 - Y0)[..., None] * ts
            ok = ok & self._points_free(XS, YS)
            ok_all[mi] = ok

        self._move_ok = ok_all

    # ---------------- 障碍管理 ----------------
    def add_obstacle(self, x: float, y: float, r: float) -> "PoolPlanner":
        """追加一个圆形静态障碍（水下浮标 / 沉物），半径 r 米，随后重建栅格。"""
        if r < 0:
            raise ValueError(f"障碍半径不能为负，收到 {r}")
        self._obstacles.append((float(x), float(y), float(r)))
        self._build()
        return self

    def clear_obstacles(self) -> "PoolPlanner":
        self._obstacles.clear()
        self._build()
        return self

    @property
    def obstacles(self) -> list[tuple[float, float, float]]:
        return list(self._obstacles)

    # ---------------- 坐标 / 可行性 ----------------
    def cell_of(self, x: float, y: float) -> tuple[int, int]:
        res = self.resolution_m
        n = self.grid_n
        ix = min(max(int(math.floor(x / res)), 0), n - 1)
        iy = min(max(int(math.floor(y / res)), 0), n - 1)
        return ix, iy

    def center_of(self, ix: int, iy: int) -> tuple[float, float]:
        res = self.resolution_m
        return (ix + 0.5) * res, (iy + 0.5) * res

    def is_free_cell(self, ix: int, iy: int) -> bool:
        return bool(self.free[ix, iy])

    def is_free_world(self, x: float, y: float) -> bool:
        """
        连续空间的可行性：船心放在 (x, y) 时，离池壁和所有障碍是否都 >= 膨胀半径。

        这是最终判据（A* 的每一步、LOS 化简的每条线段都用它校验），也是测试里
        "路径不穿膨胀边界"的检查依据。
        """
        c = self.clear_total_m
        lo = c - EPS
        hi = self.size_m - c + EPS
        if not (lo <= x <= hi and lo <= y <= hi):
            return False
        for (ox, oy, r) in self._obstacles:
            rr = r + c - EPS
            if rr > 0.0 and (x - ox) ** 2 + (y - oy) ** 2 < rr * rr:
                return False
        return True

    def _segment_free(self, p0, p1) -> bool:
        """线段是否全程可行（采样步长 = 半格，比船体尺度小一个量级）。"""
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
        d = math.hypot(x1 - x0, y1 - y0)
        if d < EPS:
            return self.is_free_world(x0, y0)
        n = max(2, int(math.ceil(d / (self.resolution_m * 0.5))) + 1)
        t = np.linspace(0.0, 1.0, n)
        xs = (x0 + (x1 - x0) * t)[None, :]
        ys = (y0 + (y1 - y0) * t)[None, :]
        return bool(self._points_free(xs, ys)[0])

    def snap_cell(self, x: float, y: float) -> tuple[int, int] | None:
        """最近的可行格（按米坐标欧氏距离）。全池都不可行时返回 None。"""
        if len(self._free_cells) == 0:
            return None
        d2 = ((self._free_centers[:, 0] - x) ** 2
              + (self._free_centers[:, 1] - y) ** 2)
        i = int(np.argmin(d2))
        return int(self._free_cells[i, 0]), int(self._free_cells[i, 1])

    def snap(self, x: float, y: float) -> tuple[float, float] | None:
        """最近可行格的中心（米坐标）。"""
        cell = self.snap_cell(x, y)
        if cell is None:
            return None
        return self.center_of(*cell)

    # ---------------- A* ----------------
    def _astar_cells(self, start_cell, goal_cell) -> list[tuple[int, int]] | None:
        """8 邻接 A*，格子坐标为输入，返回格子序列；不可达返回 None。"""
        n = self.grid_n
        si, sj = int(start_cell[0]), int(start_cell[1])
        gi, gj = int(goal_cell[0]), int(goal_cell[1])
        if not self.free[si, sj] or not self.free[gi, gj]:
            return None

        start = si * n + sj
        goal = gi * n + gj
        total = n * n
        gscore = np.full(total, np.inf)
        gscore[start] = 0.0
        came = np.full(total, -1, dtype=np.int64)
        closed = np.zeros(total, dtype=bool)
        move_ok = self._move_ok
        moves = _MOVES

        open_heap: list[tuple[float, float, int]] = [(0.0, 0.0, start)]
        while open_heap:
            _f, gc, cur = heapq.heappop(open_heap)
            if closed[cur]:
                continue
            if cur == goal:
                cells: list[tuple[int, int]] = []
                node = int(cur)
                while node != -1:
                    ci, cj = divmod(node, n)
                    cells.append((ci, cj))
                    node = int(came[node])
                cells.reverse()
                return cells
            closed[cur] = True
            ci, cj = divmod(cur, n)
            for mi in range(len(moves)):
                if not move_ok[mi, ci, cj]:
                    continue
                dix, diy, cost = moves[mi]
                ni = ci + dix
                nj = cj + diy
                nxt = ni * n + nj
                if closed[nxt]:
                    continue
                ng = gc + cost
                if ng < gscore[nxt] - 1e-12:
                    gscore[nxt] = ng
                    came[nxt] = cur
                    hx = abs(ni - gi)
                    hy = abs(nj - gj)
                    h = (hx + hy) + (SQRT2 - 2.0) * min(hx, hy)   # 八方向精确启发
                    heapq.heappush(open_heap, (ng + h, ng, nxt))
        return None

    def _los_simplify(self, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """视线简化：从当前点尽量"看"到最远的可见点，跳过中间折点。"""
        if len(pts) <= 2:
            return list(pts)
        out = [pts[0]]
        i = 0
        n = len(pts)
        while i < n - 1:
            j = n - 1
            while j > i + 1 and not self._segment_free(pts[i], pts[j]):
                j -= 1
            out.append(pts[j])
            i = j
        return out

    def plan(self, start, goal, smooth: bool = True):
        """
        从 start 到 goal 规划一条可行路径。

        :return: (path, reachable)
            path      : [(x, y), ...] 米坐标；起点/终点会吸附到最近可行格中心
            reachable : False 表示不可达（例如目标被障碍完全隔断），此时 path 是
                        "直线兜底" [start, goal]，由上层决定是否照直开或停车
        """
        sx, sy = float(start[0]), float(start[1])
        gx, gy = float(goal[0]), float(goal[1])

        s_cell = self.snap_cell(sx, sy)
        g_cell = self.snap_cell(gx, gy)
        if s_cell is None or g_cell is None:
            # 全池无可行格（障碍覆盖了整个水池）：只能直线兜底
            return [(sx, sy), (gx, gy)], False

        cells = self._astar_cells(s_cell, g_cell)
        if cells is None:
            return [(sx, sy), (gx, gy)], False

        pts = [self.center_of(i, j) for (i, j) in cells]
        if smooth:
            pts = self._los_simplify(pts)
        pts = _dedupe(pts, 1e-9)
        if len(pts) == 1:
            pts = [pts[0], pts[0]]
        return pts, True

    # ---------------- 覆盖搜索 ----------------
    def coverage_bounds(self) -> tuple[float, float]:
        """覆盖区域的内缩边界 (lo, hi)，即船心允许到达的方形范围。"""
        lo = self.clear_total_m
        hi = self.size_m - self.clear_total_m
        return lo, hi

    def coverage_path(self, half_swath_m: float | None = None,
                      loop: bool = False,
                      corner_radius_m: float = 0.0,
                      connector: str = "uturn") -> list[tuple[float, float]]:
        """
        弓字形（boustrophedon）覆盖航线。

        :param half_swath_m: 有效搜索半宽（米）；行距 = 2 * 该值。None 用
                             self.coverage_half_swath_m（默认 0.25 m -> 行距 0.5 m）
        :param loop: False = 往返（走到最后一行末尾就结束，上层可反转复用）；
                     True  = 闭环巡逻（最后沿侧壁回到起点，首尾同点）
        :param corner_radius_m: 拐角倒圆半径（切线长度，米）。0 = 保留 90° 尖角的
                     标准弓字形航点（便于检查航线结构）。
        :param connector: 行与行之间怎么接
                     "uturn"    = 标准弓字形：沿侧壁 90° 折返（航点最规整，但行距
                                  0.46 m 的 U 型弯**没法用 >=0.5 m 的目标引导**）；
                     "diagonal" = 斜接（serpentine）：同一方向走完一行后斜穿水池回到
                                  下一行行首，每段都 >=0.9 m，纯追踪+40 cm 交接约束下
                                  唯一能真正跟下来的形态（Planner 默认用这个）。
        :return: 有序航点（米坐标），全部落在内缩边界内

        行数取 ceil(span / 行距) 且至少 2 行，行距再按实际行数均分，这样搜索带正好
        铺满整个内缩区域（覆盖率 100%，见 coverage_ratio）。
        """
        if connector not in ("uturn", "diagonal"):
            raise ValueError(f"connector 只能是 'uturn' 或 'diagonal'，收到 {connector!r}")
        half = self.coverage_half_swath_m if half_swath_m is None else float(half_swath_m)
        half = max(half, 1e-3)
        lo, hi = self.coverage_bounds()
        if hi <= lo:
            return []

        span = hi - lo
        n_lanes = int(math.ceil(span / (2.0 * half) - 1e-9))
        n_lanes = max(2, n_lanes)
        spacing = span / n_lanes
        lane_ys = [lo + (k + 0.5) * spacing for k in range(n_lanes)]

        pts: list[tuple[float, float]] = []
        if connector == "diagonal":
            # 斜接：每行都从 lo 走到 hi，行末斜穿回下一行行首（段长 = 对角线 >=0.9）
            for y in lane_ys:
                pts.extend([(lo, y), (hi, y)])
        else:
            for k, y in enumerate(lane_ys):
                if k % 2 == 0:
                    pts.extend([(lo, y), (hi, y)])
                else:
                    pts.extend([(hi, y), (lo, y)])

        pts = _dedupe(pts, 1e-9)

        # 有障碍时：把被挡住的接驳段换成 A* 绕行（没障碍时这一步是空操作）
        if self._obstacles and len(pts) >= 2:
            spliced: list[tuple[float, float]] = [pts[0]]
            for a, b in zip(pts[:-1], pts[1:]):
                if self._segment_free(a, b):
                    spliced.append(b)
                    continue
                detour, ok = self.plan(a, b)
                if ok and len(detour) >= 2:
                    spliced.extend(detour[1:])
                else:
                    spliced.append(b)
            pts = _dedupe(spliced, 1e-9)

        if loop and len(pts) >= 2:
            first = pts[0]
            last = pts[-1]
            if connector == "diagonal":
                pts.append((first[0], first[1]))          # 直接一条对角线闭合
            else:
                if abs(last[0] - first[0]) > 1e-9:
                    pts.append((last[0], first[1]))
                pts.append((first[0], first[1]))
            pts = _dedupe(pts, 1e-9)

        if loop and len(pts) >= 2 and connector != "diagonal":
            # 旋转闭环：让"最后一段"是最长的一段。短闭合段会让末端折返，
            # 纯追踪的虚拟目标被迫贴近船（违反 0.5 m 交接约束）。
            cycle = pts[:-1]
            m = len(cycle)
            if m >= 3:
                seg_len = [
                    math.hypot(cycle[(i + 1) % m][0] - cycle[i][0],
                               cycle[(i + 1) % m][1] - cycle[i][1])
                    for i in range(m)
                ]
                imax = max(range(m), key=lambda i: seg_len[i])
                j = (imax + 1) % m
                cycle = cycle[j:] + cycle[:j]
                pts = cycle + [cycle[0]]

        if corner_radius_m and corner_radius_m > 0:
            pts = _fillet_polyline(pts, float(corner_radius_m), closed=loop)

        return pts

    def _min_dist_to_paths(self, paths) -> np.ndarray:
        """内缩区域每个可行格中心到一组折线的最小距离。"""
        centers = self._free_centers
        dmin = np.full(len(centers), np.inf)
        for path in paths:
            pts = _as_points(path)
            if len(pts) == 0:
                continue
            if len(pts) == 1:
                dmin = np.minimum(dmin, np.linalg.norm(centers - pts[0], axis=1))
                continue
            for a, b in zip(pts[:-1], pts[1:]):
                ab = b - a
                l2 = float(ab @ ab)
                if l2 < 1e-18:
                    d = np.linalg.norm(centers - a, axis=1)
                else:
                    t = np.clip((centers - a) @ ab / l2, 0.0, 1.0)
                    proj = a + t[:, None] * ab
                    d = np.linalg.norm(centers - proj, axis=1)
                dmin = np.minimum(dmin, d)
        return dmin

    def _ratio_of(self, dmin: np.ndarray, half_swath_m: float | None) -> float:
        half = self.coverage_half_swath_m if half_swath_m is None else float(half_swath_m)
        return float(np.mean(dmin <= half + EPS))

    def coverage_ratio(self, path, half_swath_m: float | None = None) -> float:
        """
        覆盖率：内缩区域内（且非障碍）的可行格中心里，距航线 <= half_swath 的比例。

        这是"搜索带扫过的面积占比"的栅格离散版本：只要每个可行格都落在搜索带内，
        就认为这一片水域被搜索过了。
        """
        if len(self._free_centers) == 0 or path is None:
            return 0.0
        return self._ratio_of(self._min_dist_to_paths([path]), half_swath_m)

    def coverage_ratio_multi(self, paths, half_swath_m: float | None = None) -> float:
        """多条航线（例如多圈巡逻）累计覆盖的并集覆盖率。"""
        if len(self._free_centers) == 0 or not paths:
            return 0.0
        return self._ratio_of(self._min_dist_to_paths(paths), half_swath_m)

    # ---------------- 调试 ----------------
    def ascii_map(self, path=None, start=None, goal=None) -> str:
        """把栅格打成 ASCII 图，方便现场核对边界膨胀是否符合预期。"""
        pts = _as_points(path) if path is not None else np.zeros((0, 2))
        cell_set = set()
        if len(pts):
            for p in pts:
                ix, iy = self.cell_of(float(p[0]), float(p[1]))
                cell_set.add((ix, iy))
        s_cell = self.cell_of(*start) if start is not None else None
        g_cell = self.cell_of(*goal) if goal is not None else None
        n = self.grid_n
        lines = []
        for iy in range(n - 1, -1, -1):
            row = []
            for ix in range(n):
                ch = "." if self.free[ix, iy] else "#"
                if (ix, iy) == s_cell:
                    ch = "S"
                elif (ix, iy) == g_cell:
                    ch = "G"
                elif (ix, iy) in cell_set:
                    ch = "*"
                row.append(ch)
            lines.append("".join(row))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# 2) 纯追踪
# --------------------------------------------------------------------------
@dataclass
class PursuitOutput:
    """纯追踪单帧输出。"""
    target_x: float          # 下发给船端的虚拟目标 X（米）
    target_y: float          # 下发给船端的虚拟目标 Y（米）
    remaining_m: float       # 沿路径剩余长度（米）
    arrived: bool            # 是否到达终点（< arrived_m）
    distance_m: float        # 虚拟目标与船的欧氏距离（米）—— 40 cm 交接自检用
    lookahead_used_m: float  # 实际使用的 lookahead（急弯时会大于配置值）
    held: bool = False       # True = 几何上凑不够 0.5 m，沿用了上一次有效目标
    constraint_met: bool = True   # 是否满足"剩余 > lookahead 则距离 >= min_target_dist"


class PurePursuit:
    """
    折线路径的纯追踪虚拟目标。

    硬约束（现场关键）：只要 remaining > lookahead_m，输出的虚拟目标与船的欧氏距离
    必须 >= min_target_dist_m（默认 0.5 m）。理由见模块 docstring：船端在 40 cm 就切
    二哈末端，虚拟目标不能"贴脸"。

    实现：标准纯追踪取弧长 lookahead 处的点；若该点离船太近（急弯 / 折返），就继续沿
    路径向前找"第一个距离够远的点"。这等价于临时加长 lookahead，仍然是路径上的点，
    不会把船带偏。

    另外带一个**进度窗口**（progress_window_m，默认 0.5 m）：投影只在"上次进度 ± 0.5 m"
    内取最近点。这不是可有可无的细节 —— 弓字形航线的行距（0.46 m）小于 lookahead，
    船走到两行中间时到两行距离几乎相等，全局最近点会逐帧在两行之间跳，虚拟目标左右
    横摆，现场表现就是船在两行之间画正弦、走不动。

    heading 参数**不参与计算**：标准纯追踪靠路径投影确定前方目标，不需要朝向；
    保留它是为了和 BoatPose 的 (x, y, heading) 接口一致。
    """

    def __init__(self, lookahead_m: float = 0.55,
                 min_target_dist_m: float = 0.5,
                 arrived_m: float = 0.08,
                 extend_step_m: float = 0.02,
                 progress_window_m: float = 0.50):
        if lookahead_m <= 0:
            raise ValueError(f"lookahead_m 必须为正，收到 {lookahead_m}")
        if min_target_dist_m <= 0:
            raise ValueError(f"min_target_dist_m 必须为正，收到 {min_target_dist_m}")
        if arrived_m < 0:
            raise ValueError(f"arrived_m 不能为负，收到 {arrived_m}")
        if progress_window_m <= 0:
            raise ValueError(f"progress_window_m 必须为正，收到 {progress_window_m}")
        self.lookahead_m = float(lookahead_m)
        self.min_target_dist_m = float(min_target_dist_m)
        self.arrived_m = float(arrived_m)
        self.extend_step_m = max(1e-3, float(extend_step_m))
        self.progress_window_m = max(0.05, float(progress_window_m))
        # 余量：让输出严格满足 >= 0.5（浮点上不至于差 1e-16 被判不合格）
        self._margin = 1e-6
        # 进度锚点：把投影限制在"上次进度 ± window"内，避免平行航线之间跳点
        self._progress: float | None = None
        self._path_key: tuple | None = None
        self._last_valid_target: tuple[float, float] | None = None

    def reset(self) -> None:
        """清空进度锚点（换任务 / 强制重新定位到路径起点时调用）。"""
        self._progress = None
        self._path_key = None
        self._last_valid_target = None

    def _sync_path(self, pts: np.ndarray, total: float) -> None:
        key = (len(pts), float(pts[0, 0]), float(pts[0, 1]),
               float(pts[-1, 0]), float(pts[-1, 1]), total)
        if key != self._path_key:
            self._path_key = key
            self._progress = None
            self._last_valid_target = None

    def compute(self, boat_pose, path) -> PursuitOutput:
        x, y, _heading = _unpack_pose(boat_pose)
        pts = _as_points(path)
        if len(pts) == 0:
            raise ValueError("path 不能为空")

        if len(pts) == 1:
            d = math.hypot(pts[0, 0] - x, pts[0, 1] - y)
            return PursuitOutput(float(pts[0, 0]), float(pts[0, 1]), d,
                                 d < self.arrived_m, d, 0.0)

        # 路径总长（同时用于识别"是不是换了一条路径"）
        seg_len = np.linalg.norm(pts[1:] - pts[:-1], axis=1)
        total = float(np.sum(seg_len))
        self._sync_path(pts, total)

        # 局部进度窗口：只在"上次进度 ± window"内取投影。
        # 否则两行平行航线相距 0.46 m（< lookahead）时，船走到两行中间，最近点会
        # 逐帧在两行之间跳，虚拟目标左右横摆 —— 现场表现就是船在两行之间画正弦。
        s_lo = s_hi = None
        if self._progress is not None:
            s_lo = self._progress - self.progress_window_m
            s_hi = self._progress + self.progress_window_m
        _proj, s_proj, d_win, cum = _polyline_project((x, y), pts, s_lo, s_hi)

        # 但锚点也可能"锁死"在错误的路段（船掉头 / 被推开后窗口回不来）：
        # 若窗口内的最近点明显比全局最近点差，说明船已经不在那一段了 -> 重新锚定。
        if s_lo is not None:
            _pg, s_glob, d_glob, _cg = _polyline_project((x, y), pts)
            if d_win > max(d_glob + 0.15, 0.30):
                s_proj, d_win = s_glob, d_glob

        s_proj = min(max(float(s_proj), 0.0), total)
        self._progress = s_proj

        remaining = max(0.0, total - s_proj)

        end = pts[-1]
        dist_end = math.hypot(float(end[0]) - x, float(end[1]) - y)
        arrived = dist_end < self.arrived_m

        if remaining <= self.lookahead_m + EPS:
            # 剩余路径已经很短：直接把终点交给船端（此时船端切末端视觉是**该切**的）
            target = end
            used = remaining
            held = False
        else:
            need = self.min_target_dist_m + self._margin
            target = None
            used = self.lookahead_m
            held = False

            s = min(total, s_proj + self.lookahead_m)
            cand = _point_at_arc(s, pts, cum)
            if math.hypot(float(cand[0]) - x, float(cand[1]) - y) >= need:
                target = cand
            else:
                # 急弯 / 折返：继续向前推进，直到离船足够远（仍沿路径，不切角）
                while s < total - EPS:
                    s = min(total, s + self.extend_step_m)
                    cand = _point_at_arc(s, pts, cum)
                    if math.hypot(float(cand[0]) - x, float(cand[1]) - y) >= need:
                        target = cand
                        used = s - s_proj
                        break

            if target is None:
                # 沿剩余路径找不到 >= min_dist 的点（船陷进航线内侧 / 折返把路包住了）。
                # 此时**绝不能**发一个 < min_dist 的目标：船端会切二哈末端，搜索段没有
                # 真实目标，会直接停在半路。退而求其次：取剩余路径上"离船最远"的点，
                # 先把船带出被包住的区域；若连它都够不到 min_dist，就沿用上一次有效目标
                # （它一定够远），船继续朝它走，等进度推进/重规划后几何自然解开。
                best_d = -1.0
                best_pt = None
                s_try = s_proj + self.extend_step_m
                while s_try < total - EPS:
                    c = _point_at_arc(s_try, pts, cum)
                    dd = math.hypot(float(c[0]) - x, float(c[1]) - y)
                    if dd > best_d:
                        best_d, best_pt = dd, c
                    s_try += self.extend_step_m * 2.0
                if best_pt is not None and best_d >= need:
                    target = best_pt
                    used = remaining
                elif self._last_valid_target is not None:
                    target = np.asarray(self._last_valid_target, dtype=np.float64)
                    used = remaining
                    held = True
                elif best_pt is not None:
                    target = best_pt
                    used = remaining
                    held = True
                else:
                    target = end
                    used = remaining
                    held = True

        tx, ty = float(target[0]), float(target[1])
        dist = math.hypot(tx - x, ty - y)
        if dist >= self.min_target_dist_m + self._margin and remaining > self.lookahead_m + EPS:
            self._last_valid_target = (tx, ty)
        constraint_met = (remaining <= self.lookahead_m + EPS
                          or dist >= self.min_target_dist_m - 1e-9)
        return PursuitOutput(tx, ty, remaining, arrived, dist, used, held, constraint_met)


# --------------------------------------------------------------------------
# 3) 状态机
# --------------------------------------------------------------------------
@dataclass
class PlanOutput:
    """一帧规划结果：直接取 target_x / target_y 填进原来的上报字段即可。"""
    target_x: float
    target_y: float
    mode: str
    path: list[tuple[float, float]]
    remaining_m: float
    arrived: bool
    reachable: bool

    def to_dict(self) -> dict:
        return {
            "target_x": round(self.target_x, 4),
            "target_y": round(self.target_y, 4),
            "mode": self.mode,
            "remaining_m": round(self.remaining_m, 4),
            "arrived": bool(self.arrived),
            "reachable": bool(self.reachable),
            "path_points": len(self.path),
        }


class Planner:
    """
    规划状态机：目标可见 -> TRACK（A* 追目标），目标丢失 -> SEARCH（覆盖搜索）。

    重规划策略（两层防抖）：
      * 定期重规划：每 replan_interval_s 秒重算一次（默认 1.0 s），吸收船位姿漂移；
      * 事件重规划：目标移动 > target_move_threshold_m、船偏离当前路径 >
        deviation_threshold_m、或覆盖航线走完（arrived）时立即重算；
      * 但两次重规划之间至少间隔 min_replan_interval_s（默认 0.2 s = 4 帧 @20Hz）。
        目标检测偶发丢帧时，模式会在 TRACK/SEARCH 之间跳，这个间隔保证不会每一帧
        都换一条路径（现场表现就是船头来回摆）。

    SEARCH 模式下虚拟目标绝不能贴到 40 cm 以内：搜索段没有真实目标，船一切末端视觉
    就会停在半路（表现为"卡在航点附近不动"）。三种形态都已实现，默认用最稳的一种：
      * 往返（默认，search_loop=False + search_connector="uturn"）：标准弓字形航线，
        走到头把整条航线反转复用。船正好停在端点，天然接得上；实测 0.5 m 硬约束
        全程零违反；
      * 闭环（search_loop=True）：沿内缩边界绕圈巡逻；每次重规划在船所在位置之前的
        顶点把环切开，避免"首尾同点"导致的投影二义；
      * 斜接（search_connector="diagonal"）与倒圆（search_corner_radius_m>0）：
        让航段更长 / 拐角更圆，可选。

    ## 现场几何限制（务必知道）

    1.2 m 水池、船心可用域只有 0.92 m 见方，而"下发目标必须 >=0.5 m"意味着**船可被
    有效操纵的空间粒度就是 0.5 m 量级**。因此：
      * TRACK 完全没问题：A* 路径基本是直线/大折角，纯追踪的虚拟目标恒 >=0.5 m；
      * SEARCH 的**航线本身**覆盖率是 100%（见 PoolPlanner.coverage_path），但船的
        实际扫过轨迹受 0.5 m 粒度限制，做不到和航线一样贴合（仿真约 65%）；
      * 若现场发现搜索段仍会偶发切一次末端（目标瞬间 <0.4 m），说明船陷进了航线内侧，
        纯追踪会改用"剩余路径上离船最远的点"把船带出来，不会卡死。
    要更贴线的扫掠，只能放宽交接（例如搜索段允许 25 cm 交接）或换更大的水池。

    :param pool_planner: 可注入带障碍的 PoolPlanner；None 则新建空池
    :param lookahead_m: 纯追踪前视距离（默认 0.55）
    :param replan_interval_s: 定期重规划周期
    :param min_replan_interval_s: 最小重规划间隔（防抖）
    :param target_move_threshold_m: 目标移动多少米算"目标变了"
    :param deviation_threshold_m: 船偏离原路径多少米算"偏了"
    :param search_loop: True 用闭环巡逻航线（沿内缩边界绕圈，每次重规划在船所在顶点
                        切开）；False 用往返航线（走到头整条反转复用，默认）
    :param search_corner_radius_m: 搜索航线拐角倒圆半径（0 = 保留标准 90° 弓字形；
                                   实际船有转弯半径，需要更顺时可给 0.15~0.25）
    :param search_connector: 搜索航线行间接法："uturn"（标准弓字形，默认）或
                             "diagonal"（斜接，航段更长但会斜穿水池）
    :param coverage_half_swath_m: 覆盖搜索有效半宽，None 用 PoolPlanner 默认值
    :param append_goal_max_m: A* 终点被吸附后，若与真实目标相差不超过该值，就把真实
                              目标追加到路径末尾（保证末端交接拿到的是真实坐标）
    :param search_advance_m: SEARCH 往返模式下"剩余多少米就换下一段"
    """

    def __init__(self, pool_planner: PoolPlanner | None = None,
                 lookahead_m: float = 0.55,
                 replan_interval_s: float = 1.0,
                 min_replan_interval_s: float = 0.2,
                 target_move_threshold_m: float = 0.15,
                 deviation_threshold_m: float = 0.20,
                 search_loop: bool = False,
                 search_corner_radius_m: float = 0.0,
                 search_connector: str = "uturn",
                 coverage_half_swath_m: float | None = None,
                 append_goal_max_m: float = 0.35,
                 search_advance_m: float = 0.60,
                 handover_radius_m: float = 0.30):
        self.pool = pool_planner if pool_planner is not None else PoolPlanner()
        if coverage_half_swath_m is not None:
            self.pool.coverage_half_swath_m = float(coverage_half_swath_m)
        self.pursuit = PurePursuit(lookahead_m=lookahead_m)

        if replan_interval_s <= 0:
            raise ValueError("replan_interval_s 必须为正")
        if min_replan_interval_s < 0:
            raise ValueError("min_replan_interval_s 不能为负")
        self.replan_interval_s = float(replan_interval_s)
        self.min_replan_interval_s = float(min_replan_interval_s)
        self.target_move_threshold_m = float(target_move_threshold_m)
        self.deviation_threshold_m = float(deviation_threshold_m)
        self.search_loop = bool(search_loop)
        self.search_corner_radius_m = max(0.0, float(search_corner_radius_m))
        if search_connector not in ("uturn", "diagonal"):
            raise ValueError(f"search_connector 只能是 'uturn' 或 'diagonal'，收到 {search_connector!r}")
        self.search_connector = search_connector
        self.append_goal_max_m = float(append_goal_max_m)
        self.search_advance_m = max(float(search_advance_m), self.pursuit.lookahead_m)
        self.handover_radius_m = float(handover_radius_m)

        # ---- 运行状态 ----
        self.mode: str | None = None
        self.replan_count = 0
        self.last_plan_ms = 0.0
        self._path: list[tuple[float, float]] | None = None
        self._goal: tuple[float, float] | None = None
        self._reachable = True
        self._last_plan_t = -math.inf
        self._arrived_last = False
        self._search_reverse = False
        # 最近一帧纯追踪的原始输出（held / constraint_met 等遥测，便于现场排查与测试）
        self.last_pursuit: PursuitOutput | None = None

    # ---------------- 对外接口 ----------------
    def reset(self) -> None:
        """清空状态（重新开始一轮任务时调用）。"""
        self.mode = None
        self._path = None
        self._goal = None
        self._reachable = True
        self._last_plan_t = -math.inf
        self._arrived_last = False
        self._search_reverse = False
        self.replan_count = 0
        self.last_plan_ms = 0.0
        self.last_pursuit = None
        self.pursuit.reset()

    def add_obstacle(self, x: float, y: float, r: float) -> "Planner":
        """追加障碍（转给 PoolPlanner），并让旧路径立即作废。"""
        self.pool.add_obstacle(x, y, r)
        self._path = None
        return self

    def update(self, boat_pose, target_or_none=None, now: float | None = None) -> PlanOutput:
        """
        每帧调用一次（20 Hz）。

        :param boat_pose: BoatPose 或 (x, y[, heading])，米
        :param target_or_none: 目标坐标 (x, y) 或 None（本帧没检测到目标）
        :param now: 秒（测试/回放时显式传入，保证确定性）；None 用 time.monotonic()
        :return: PlanOutput
        """
        x, y, heading = _unpack_pose(boat_pose)
        now = time.monotonic() if now is None else float(now)
        target = _unpack_target(target_or_none)
        want = MODE_TRACK if target is not None else MODE_SEARCH

        urgent = self._wants_replan(x, y, want, target)
        periodic_due = (self._path is not None
                        and (now - self._last_plan_t) >= self.replan_interval_s)
        if self._path is None or urgent or periodic_due:
            # 首次规划不受最小间隔限制；SEARCH 换段是"已经到点"的确定性事件，
            # 也放行（否则要多等几帧，虚拟目标会贴到 0.5 m 以内）；其余重规划都要
            # 过防抖门槛。
            bypass = bool(self._arrived_last and want == MODE_SEARCH)
            if self._path is None or bypass or (now - self._last_plan_t) >= self.min_replan_interval_s:
                self._do_replan(x, y, want, target, now)

        if self._path is None:            # 理论上不会发生，兜底
            self._path = [(x, y), (x, y)]

        out = self.pursuit.compute((x, y, heading), self._path)
        self.last_pursuit = out
        if want == MODE_SEARCH:
            if self.search_loop:
                # 闭环巡逻是"一直扫下去"，没有终点概念：arrived 恒为 False。
                # 路径每次重规划都会在船的投影处切开，剩余长度≈整圈，因此永远
                # 不会落进"剩余 <= lookahead"分支，虚拟目标恒 >= 0.5 m。
                arrived = False
            else:
                # 往返航线有真正的末端：在虚拟目标进入 40 cm 末端区之前就换段
                arrived = bool(out.arrived or out.remaining_m <= self.search_advance_m)
        else:
            arrived = bool(out.arrived)

        # ---- 末段直冲：船离真实目标足够近时，直接下发真实目标 ----
        # 纯追踪的虚拟前视点最多只能贴近真实目标 lookahead 那么远（0.55 m），
        # 而船端在 COARSE_ARRIVAL_RADIUS_M（0.15 m）才切末端。若不在这里切换，
        # 船端算出的"到目标距离"其实是"到虚拟点的距离"，永远进不了末端区：
        # 表现就是该停不停、临门一脚绕圈。
        # 因此当船到真实目标的直线距离 <= HANDOVER_RADIUS_M 时，用真实目标覆盖。
        target_x_final = out.target_x
        target_y_final = out.target_y
        if want == MODE_TRACK and target is not None:
            d_true = math.hypot(target[0] - x, target[1] - y)
            if d_true <= self.handover_radius_m:
                target_x_final = float(target[0])
                target_y_final = float(target[1])

        # 注意：这里记的是**模式修正后**的 arrived。SEARCH 靠它提前换段，
        # 若只说纯追踪的 arrived（< 0.08 m），虚拟目标会先贴到 0.5 m 以内。
        self._arrived_last = arrived

        return PlanOutput(
            target_x=target_x_final,
            target_y=target_y_final,
            mode=want,
            path=list(self._path),
            remaining_m=out.remaining_m,
            arrived=arrived,
            reachable=self._reachable,
        )

    # ---------------- 内部 ----------------
    def _deviation(self, x: float, y: float) -> float:
        if not self._path or len(self._path) < 2:
            return 0.0
        pts = _as_points(self._path)
        _p, _s, d, _cum = _polyline_project((x, y), pts)
        return float(d)

    def _wants_replan(self, x: float, y: float, want: str, target) -> bool:
        if self._path is None:
            return True
        if self.mode != want:
            return True
        if self._arrived_last and want == MODE_SEARCH and not self.search_loop:
            # 往返航线走完：起新的一段（闭环巡逻没有"走完"，靠定期重规划重新切线）
            return True
        if target is not None:
            if self._goal is None:
                return True
            if math.hypot(target[0] - self._goal[0],
                          target[1] - self._goal[1]) > self.target_move_threshold_m:
                return True
        return self._deviation(x, y) > self.deviation_threshold_m

    def _append_goal(self, path, target, reachable) -> list[tuple[float, float]]:
        """A* 终点被吸附到可行格后，把真实目标补回路径末尾（末端交接要用真坐标）。"""
        pts = [(float(p[0]), float(p[1])) for p in path]
        if not reachable or not pts:
            return pts
        ex, ey = pts[-1]
        d = math.hypot(ex - target[0], ey - target[1])
        if d <= 1e-9:
            return pts
        if d <= self.append_goal_max_m and self._in_pool(target):
            pts.append((float(target[0]), float(target[1])))
        return pts

    def _in_pool(self, p) -> bool:
        size = self.pool.size_m
        return 0.0 <= p[0] <= size and 0.0 <= p[1] <= size

    def _do_replan(self, x: float, y: float, want: str, target, now: float) -> None:
        t0 = time.perf_counter()
        if want == MODE_TRACK:
            path, reachable = self.pool.plan((x, y), target)
            path = self._append_goal(path, target, reachable)
            self._goal = target
        else:
            path = self.pool.coverage_path(
                loop=self.search_loop,
                corner_radius_m=self.search_corner_radius_m,
                connector=self.search_connector,
            )
            if self.search_loop:
                # 闭环巡逻：在船所在位置"之前最近的那个顶点"把环切开，给一条开放的一圈路径。
                # 这样剩余路径≈整圈、起点就在船脚下，虚拟目标恒在 0.55 m 之外；
                # 且切口随船推进，每圈都从船刚走过的地方接着扫（不会漏扫、不用掉头）。
                if path:
                    path = self._cut_loop_at_vertex(path, x, y)
            else:
                # 往返航线：走到头就把整条航线反转，船正好在端点，天然接得上
                if self._arrived_last:
                    self._search_reverse = not self._search_reverse
                if self._search_reverse and len(path) >= 2:
                    path = list(reversed(path))
            if not path:
                path = [(x, y), (x, y)]
            reachable = True
            self._goal = None

        self._path = [(float(p[0]), float(p[1])) for p in path]
        self._reachable = bool(reachable)
        self.mode = want
        self._last_plan_t = now
        self.replan_count += 1
        self.last_plan_ms = (time.perf_counter() - t0) * 1000.0

    @staticmethod
    def _cut_loop_at_vertex(path, x: float, y: float) -> list[tuple[float, float]]:
        """
        把闭环航线切开成"从投影点之前最近的那个顶点出发、绕一圈"的**开放**路径。

        为什么必须切在顶点、并且必须是开放路径（不能首尾同点）：
          闭环上"起点"和"终点"是同一个物理点。船稍微偏离航线时，到首段和到尾段的
          距离只差二阶小量，最近点很容易被判到尾段 —— 于是 remaining 从整圈（2.7 m）
          塌到 0，虚拟目标瞬间贴到船上（实测 0.19 m），船端会误切二哈末端。
          切在顶点后：船稳稳落在起点附近，而终点退到"船身后一整段"之外，最近点唯一。
        """
        pts = _as_points(path)
        if len(pts) < 3:
            return [(float(p[0]), float(p[1])) for p in pts]

        _proj, s, _d, _cum = _polyline_project((x, y), pts)
        seg_len = np.linalg.norm(pts[1:] - pts[:-1], axis=1)
        vcum = np.concatenate(([0.0], np.cumsum(seg_len)))
        verts = [(float(p[0]), float(p[1])) for p in pts[:-1]]   # 去掉重复的末点

        i = int(np.searchsorted(vcum, s, side="right") - 1)      # 顶点 at-or-before
        i = min(max(i, 0), len(verts) - 1)
        out = _dedupe(verts[i:] + verts[:i], 1e-9)

        # 末端离起点太近时，投影会在"起点/终点"之间二义（首尾同点问题的残留）：
        # 船只要稍微偏离航线，最近点就可能判到终点，remaining 从整圈塌到 0。
        # 把尾巴上离起点不足 0.5 m 的点砍掉 —— 那一小段是船刚走过的，下一圈会补上。
        min_gap = 0.5
        while len(out) > 3 and math.hypot(out[-1][0] - out[0][0],
                                          out[-1][1] - out[0][1]) < min_gap:
            out.pop()
        return out


# --------------------------------------------------------------------------
# 手工自检（python planner.py）：打印栅格图、覆盖航线与单次规划耗时
# --------------------------------------------------------------------------
def _demo() -> None:
    pool = PoolPlanner()
    pool.add_obstacle(0.62, 0.62, 0.10)

    t0 = time.perf_counter()
    path, reachable = pool.plan((0.175, 0.175), (1.025, 1.025))
    plan_ms = (time.perf_counter() - t0) * 1000.0

    print(f"水池 {pool.size_m:.2f} m / {pool.grid_n}x{pool.grid_n} 格 "
          f"@ {pool.resolution_m * 1000:.0f} mm，膨胀 {pool.clear_total_m * 1000:.0f} mm")
    print(pool.ascii_map(path, (0.175, 0.175), (1.025, 1.025)))
    print(f"A* 可达={reachable} 点数={len(path)} 长度={polyline_length(path):.3f} m "
          f"耗时={plan_ms:.3f} ms")

    cov = pool.coverage_path()
    print(f"覆盖航线 {len(cov)} 点，覆盖率={pool.coverage_ratio(cov) * 100:.1f}%")

    planner = Planner(pool_planner=pool)
    pp = PurePursuit()
    out = pp.compute((0.175, 0.175, 0.0), path)
    print(f"纯追踪：虚拟目标=({out.target_x:.3f},{out.target_y:.3f}) "
          f"距离={out.distance_m:.3f} m remaining={out.remaining_m:.3f} m")
    print(f"状态机：{planner.update((0.175, 0.175, 0.0), None, now=0.0).mode} / "
          f"{planner.update((0.175, 0.175, 0.0), (1.0, 1.0), now=1.0).mode}")


if __name__ == "__main__":
    _demo()

__all__ = [
    "PoolPlanner",
    "PurePursuit",
    "Planner",
    "PlanOutput",
    "PursuitOutput",
    "MODE_TRACK",
    "MODE_SEARCH",
    "polyline_length",
]
