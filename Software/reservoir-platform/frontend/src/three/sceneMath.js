/**
 * 全景大坝场景的纯数学工具
 *
 * 这些函数不依赖 three，也不碰 DOM，因此既能在浏览器里用，
 * 也能在 Node 下直接跑单测（见 tests/sceneMath.test.mjs）。
 * 水位→世界坐标、闸门状态→开度、相机位姿插值都在这里，
 * 保证「渲染层怎么变，业务换算不变」。
 */

/** 水位锚点：世界坐标里死水位/设计水位/汛限水位对应的高度（米） */
export const WATER_ANCHORS = Object.freeze({ dieY: 6, designY: 16, floodY: 22 })

/** 没有任何阈值可用时，按这个区间做演示映射 */
export const FALLBACK_LEVEL_RANGE = Object.freeze({ min: 0, max: 3 })

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value))
}

export function lerp(a, b, t) {
  return a + (b - a) * t
}

/** 指数阻尼：与帧率无关的平滑（lambda 越大越快） */
export function damp(current, target, lambda, dt) {
  if (!Number.isFinite(dt) || dt <= 0) return current
  return lerp(current, target, 1 - Math.exp(-lambda * dt))
}

export function smoothstep(edge0, edge1, x) {
  if (edge0 === edge1) return x < edge0 ? 0 : 1
  const t = clamp((x - edge0) / (edge1 - edge0), 0, 1)
  return t * t * (3 - 2 * t)
}

export function easeInOutCubic(t) {
  const x = clamp(t, 0, 1)
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2
}

/** 把后端/MQTT 的松散数值（字符串、null、NaN）解析成 number | null */
export function parseNumber(value) {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(String(value).trim())
  return Number.isFinite(n) ? n : null
}

/**
 * 水位（米）→ 水面世界高度（米）
 *
 * 用「死水位 / 设计水位 / 汛限水位」三个锚点做分段线性映射，
 * 缺锚点时退化为以设计水位为中心的 0.8 单位/米比例，全部缺失时用
 * FALLBACK_LEVEL_RANGE。无论如何都夹在 [2, 26] 之间，避免水面穿模。
 */
export function levelToY(level, thresholds = {}, anchors = WATER_ANCHORS) {
  const value = parseNumber(level)
  if (value === null) return anchors.designY

  const pairs = []
  const die = parseNumber(thresholds.die)
  const design = parseNumber(thresholds.design)
  const flood = parseNumber(thresholds.flood)
  if (die !== null) pairs.push([die, anchors.dieY])
  if (design !== null) pairs.push([design, anchors.designY])
  if (flood !== null) pairs.push([flood, anchors.floodY])

  const sorted = pairs
    .filter(([lv]) => Number.isFinite(lv))
    .sort((a, b) => a[0] - b[0])

  let y
  if (sorted.length >= 2) {
    if (value <= sorted[0][0]) y = sorted[0][1] - (sorted[0][0] - value) * 0.8
    else if (value >= sorted[sorted.length - 1][0]) {
      const last = sorted[sorted.length - 1]
      y = last[1] + (value - last[0]) * 0.8
    } else {
      y = sorted[sorted.length - 1][1]
      for (let i = 0; i < sorted.length - 1; i += 1) {
        const [x0, y0] = sorted[i]
        const [x1, y1] = sorted[i + 1]
        if (value >= x0 && value <= x1) {
          y = lerp(y0, y1, (value - x0) / (x1 - x0 || 1))
          break
        }
      }
    }
  } else if (sorted.length === 1) {
    const [x0, y0] = sorted[0]
    y = y0 + (value - x0) * 0.8
  } else {
    const { min, max } = FALLBACK_LEVEL_RANGE
    y = lerp(anchors.dieY, anchors.floodY, clamp((value - min) / (max - min), 0, 1))
  }

  return clamp(y, 2, 26)
}

/**
 * 水位状态：unknown / low / normal / high / flood
 * 阈值缺省时一律 normal（宁可不报警，也不误报）。
 */
export function levelStatus(level, thresholds = {}) {
  const value = parseNumber(level)
  if (value === null) return 'unknown'
  const die = parseNumber(thresholds.die)
  const design = parseNumber(thresholds.design)
  const flood = parseNumber(thresholds.flood)
  if (flood !== null && value >= flood) return 'flood'
  if (design !== null && value >= design) return 'high'
  if (die !== null && value <= die) return 'low'
  return 'normal'
}

export const LEVEL_STATUS_META = Object.freeze({
  unknown: { label: '水位未知', tone: 'neutral' },
  low: { label: '低于死水位', tone: 'warn' },
  normal: { label: '运行正常', tone: 'ok' },
  high: { label: '超设计水位', tone: 'warn' },
  flood: { label: '超汛限水位', tone: 'danger' },
})

/** 单个闸门状态（1/0/'1'/true/null）→ 开度 0..1 */
export function gateOpenRatio(state) {
  if (state === null || state === undefined || state === '') return 0
  if (state === true || state === 1 || state === '1') return 1
  return 0
}

/** 6 路闸门状态数组 → 6 个 0..1 开度 */
export function gatesToRatios(gates) {
  return Array.from({ length: 6 }, (_, i) => gateOpenRatio(gates?.[i]))
}

export function formatLevel(level, digits = 2) {
  const value = parseNumber(level)
  if (value === null) return '--'
  return value.toFixed(digits)
}

/**
 * 由「相机位置 + 观察点」推导球坐标位姿
 * @returns {{target: number[], distance: number, azimuth: number, polar: number}}
 */
export function poseFromLookAt(position, target) {
  const [px, py, pz] = position
  const [tx, ty, tz] = target
  const ox = px - tx
  const oy = py - ty
  const oz = pz - tz
  const distance = Math.max(1, Math.hypot(ox, oy, oz))
  return {
    target: [tx, ty, tz],
    distance,
    azimuth: Math.atan2(ox, oz),
    polar: Math.acos(clamp(oy / distance, -1, 1)),
  }
}

/** 位姿插值（角度走最短路径），t 为原始进度（内部做缓动） */
export function blendPose(from, to, t) {
  const k = easeInOutCubic(t)
  let dAz = to.azimuth - from.azimuth
  while (dAz > Math.PI) dAz -= Math.PI * 2
  while (dAz < -Math.PI) dAz += Math.PI * 2
  return {
    target: [
      lerp(from.target[0], to.target[0], k),
      lerp(from.target[1], to.target[1], k),
      lerp(from.target[2], to.target[2], k),
    ],
    distance: lerp(from.distance, to.distance, k),
    azimuth: from.azimuth + dAz * k,
    polar: lerp(from.polar, to.polar, k),
  }
}

/** 球坐标位姿 → 相机位置 */
export function positionFromPose(pose) {
  const { target, distance, azimuth, polar } = pose
  const sinP = Math.sin(polar)
  return [
    target[0] + distance * sinP * Math.sin(azimuth),
    target[1] + distance * Math.cos(polar),
    target[2] + distance * sinP * Math.cos(azimuth),
  ]
}

/** 相对上游面的闸门开度 → 泄流量占比（仅用于视觉与文案，不做水利计算） */
export function dischargeRatio(ratios) {
  if (!Array.isArray(ratios) || ratios.length === 0) return 0
  return ratios.reduce((sum, r) => sum + clamp(r, 0, 1), 0) / ratios.length
}
