/**
 * 通知提示音。
 *
 * 浏览器禁止在用户交互前自动播放音频，所以首次点击/按键时解锁 AudioContext；
 * 之后收到通知就能直接响。没有 AudioContext 的环境（或用户未交互）静默失败，
 * 不影响弹窗本身。
 */

let audioContext = null

function context() {
  if (typeof window === 'undefined') return null
  const AudioCtor = window.AudioContext || window.webkitAudioContext
  if (!AudioCtor) return null
  if (!audioContext) audioContext = new AudioCtor()
  return audioContext
}

function unlock() {
  const ctx = context()
  if (ctx && ctx.state === 'suspended') ctx.resume().catch(() => {})
}

if (typeof window !== 'undefined') {
  ['pointerdown', 'keydown', 'touchstart'].forEach((event) => {
    window.addEventListener(event, unlock, { once: true, passive: true })
  })
}

/** 播放两声（严重级别三声）短提示音；level 越低越柔和 */
export function playNoticeSound(level = 1) {
  const ctx = context()
  if (!ctx) return
  if (ctx.state === 'suspended') ctx.resume().catch(() => {})
  const critical = Number(level) >= 3
  const offsets = critical ? [0, 0.2, 0.4] : [0, 0.22]
  const now = ctx.currentTime
  offsets.forEach((offset) => {
    const oscillator = ctx.createOscillator()
    const gain = ctx.createGain()
    oscillator.type = 'sine'
    oscillator.frequency.value = critical ? 880 : 660
    gain.gain.setValueAtTime(0.0001, now + offset)
    gain.gain.exponentialRampToValueAtTime(0.16, now + offset + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + offset + 0.18)
    oscillator.connect(gain)
    gain.connect(ctx.destination)
    oscillator.start(now + offset)
    oscillator.stop(now + offset + 0.2)
  })
}
