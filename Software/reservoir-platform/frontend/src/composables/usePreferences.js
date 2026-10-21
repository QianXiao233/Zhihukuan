// 用户偏好：字号与语音播报设置，持久化到 localStorage
import { ref, watch } from 'vue'

/**
 * 字号档位 → 缩放系数
 * @type {Record<import('../types.js').FontSizeLevel, number>}
 */
export const FONT_SCALE = {
  small: 0.875,
  normal: 1,
  large: 1.15,
  xlarge: 1.3,
}

/**
 * 字号档位的中文说明
 * @type {Record<import('../types.js').FontSizeLevel, string>}
 */
export const FONT_LABEL = {
  small: '小',
  normal: '标准',
  large: '大',
  xlarge: '特大',
}

const FONT_KEY = 'reservoir_font_size'
/** 语音播报偏好（开关与语速） */
const VOICE_KEY = 'reservoir_voice_prefs'

/**
 * @template T
 * @param {string} key
 * @param {T} fallback
 * @returns {T}
 */
function readStored(key, fallback) {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return fallback
    return JSON.parse(raw)
  } catch {
    return fallback
  }
}

/**
 * @param {string} key
 * @param {unknown} value
 */
function writeStored(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
  } catch {
    // 存储不可用时静默忽略
  }
}

// ─────────── 字号 ───────────

const storedFont = readStored(FONT_KEY, 'normal')

/**
 * 当前字号档位
 * @type {import('vue').Ref<import('../types.js').FontSizeLevel>}
 */
export const fontSize = ref(
  Object.keys(FONT_SCALE).includes(storedFont) ? storedFont : 'normal',
)

/** 把缩放写进 CSS 变量，全站文字随之一并缩放 */
function applyFontScale() {
  const scale = FONT_SCALE[fontSize.value] ?? 1
  document.documentElement.style.setProperty('--chat-font-scale', String(scale))
}

/**
 * 设置字号档位（供组件调用）
 * @param {import('../types.js').FontSizeLevel} level
 */
export function setFontSize(level) {
  fontSize.value = level
}

watch(fontSize, (level) => {
  writeStored(FONT_KEY, level)
  applyFontScale()
})

/** 应用启动时调用一次 */
export function initPreferences() {
  applyFontScale()
}

// ─────────── 语音播报 ───────────

/**
 * @typedef {Object} VoicePrefs
 * @property {boolean} enabled
 * @property {number} rate
 */

/** @type {VoicePrefs} */
const storedVoice = readStored(VOICE_KEY, { enabled: true, rate: 1 })

/** @type {import('vue').Ref<boolean>} */
export const voiceEnabled = ref(storedVoice.enabled !== false)

/** @type {import('vue').Ref<number>} */
export const voiceRate = ref(
  typeof storedVoice.rate === 'number' && storedVoice.rate >= 0.5 && storedVoice.rate <= 1.5
    ? storedVoice.rate
    : 1,
)

watch([voiceEnabled, voiceRate], () => {
  writeStored(VOICE_KEY, { enabled: voiceEnabled.value, rate: voiceRate.value })
})

/**
 * 设置语音播报开关（供组件调用）
 * @param {boolean} value
 */
export function setVoiceEnabled(value) {
  voiceEnabled.value = value
}

/**
 * 设置语音播报语速（供组件调用）
 * @param {number} value
 */
export function setVoiceRate(value) {
  voiceRate.value = value
}
