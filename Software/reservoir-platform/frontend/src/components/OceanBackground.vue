<template>
  <div class="ocean-bg" aria-hidden="true">
    <div class="ocean-bg__blob ocean-bg__blob--1"></div>
    <div class="ocean-bg__blob ocean-bg__blob--2"></div>
    <div class="ocean-bg__blob ocean-bg__blob--3"></div>

    <!-- 漂浮粒子 / 气泡 -->
    <canvas ref="canvasRef" class="ocean-bg__canvas"></canvas>

    <!-- 水波层 -->
    <div class="ocean-bg__waves">
      <svg class="ocean-bg__wave ocean-bg__wave--1" viewBox="0 0 2880 320" preserveAspectRatio="none">
        <path
          fill="rgba(126,232,245,0.55)"
          d="M0,160 C240,220 480,100 720,160 C960,220 1200,100 1440,160 C1680,220 1920,100 2160,160 C2400,220 2640,100 2880,160 L2880,320 L0,320 Z"
        />
      </svg>
      <svg class="ocean-bg__wave ocean-bg__wave--2" viewBox="0 0 2880 320" preserveAspectRatio="none">
        <path
          fill="rgba(79,211,232,0.6)"
          d="M0,200 C300,120 600,260 900,190 C1200,120 1500,260 1800,190 C2100,120 2400,260 2700,190 L2880,190 L2880,320 L0,320 Z"
        />
      </svg>
      <svg class="ocean-bg__wave ocean-bg__wave--3" viewBox="0 0 2880 320" preserveAspectRatio="none">
        <path
          fill="rgba(18,168,196,0.5)"
          d="M0,240 C360,180 720,290 1080,240 C1440,190 1800,300 2160,250 C2520,200 2700,260 2880,240 L2880,320 L0,320 Z"
        />
      </svg>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'

/** 每多少像素面积分配一个气泡 */
const AREA_PER_BUBBLE = 26000
const MAX_BUBBLES = 70

const canvasRef = ref(null)
/** @type {(() => void) | null} */
let cleanup = null

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  let rafId = 0
  let running = false
  let width = 0
  let height = 0
  let bubbles = []

  const makeBubble = (fromBottom = false) => ({
    x: Math.random() * width,
    y: fromBottom ? height + Math.random() * 60 : Math.random() * height,
    r: 1.2 + Math.random() * 3.4,
    // 气泡上浮（y 递减），带轻微横向摆动
    vy: -(0.16 + Math.random() * 0.42),
    vx: (Math.random() - 0.5) * 0.18,
    alpha: 0.14 + Math.random() * 0.4,
  })

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    width = canvas.clientWidth || window.innerWidth
    height = canvas.clientHeight || window.innerHeight
    canvas.width = Math.floor(width * dpr)
    canvas.height = Math.floor(height * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)

    const count = Math.min(
      MAX_BUBBLES,
      Math.max(24, Math.round((width * height) / AREA_PER_BUBBLE)),
    )
    bubbles = Array.from({ length: count }, () => makeBubble())
  }

  const step = () => {
    ctx.clearRect(0, 0, width, height)

    for (const b of bubbles) {
      b.y += b.vy
      b.x += b.vx
      // 浮出顶部后从底部重新进入
      if (b.y < -12) Object.assign(b, makeBubble(true))
      if (b.x < -12) b.x = width + 12
      if (b.x > width + 12) b.x = -12

      // 气泡：中心亮、边缘收敛的柔和光点
      const gradient = ctx.createRadialGradient(b.x, b.y, 0, b.x, b.y, b.r * 3.2)
      gradient.addColorStop(0, `rgba(200, 244, 252, ${b.alpha.toFixed(3)})`)
      gradient.addColorStop(0.55, `rgba(126, 232, 245, ${(b.alpha * 0.5).toFixed(3)})`)
      gradient.addColorStop(1, 'rgba(79, 211, 232, 0)')
      ctx.fillStyle = gradient
      ctx.beginPath()
      ctx.arc(b.x, b.y, b.r * 3.2, 0, Math.PI * 2)
      ctx.fill()
    }

    rafId = requestAnimationFrame(step)
  }

  const start = () => {
    if (running) return
    running = true
    rafId = requestAnimationFrame(step)
  }

  const stop = () => {
    running = false
    cancelAnimationFrame(rafId)
  }

  const onVisibility = () => {
    if (document.hidden) stop()
    else start()
  }

  resize()
  start()
  window.addEventListener('resize', resize)
  document.addEventListener('visibilitychange', onVisibility)

  cleanup = () => {
    stop()
    window.removeEventListener('resize', resize)
    document.removeEventListener('visibilitychange', onVisibility)
  }
})

onBeforeUnmount(() => {
  cleanup?.()
  cleanup = null
})
</script>

<style scoped src="./OceanBackground.css"></style>
