<template>
  <div ref="tileEl" class="video-tile" :class="[`is-${status}`, { 'is-fullscreen': isFullscreen }]">
    <video ref="videoEl" class="video-tile__video" autoplay muted playsinline></video>
    <div class="video-tile__vignette"></div>

    <header class="video-tile__head">
      <span class="video-tile__live"><i></i>{{ stateText }}</span>
      <span class="video-tile__protocol">{{ protocolLabel }}</span>
    </header>

    <footer class="video-tile__foot">
      <div class="video-tile__meta">
        <strong>{{ source.sourceName }}</strong>
        <small>{{ source.location || '未填写安装位置' }}</small>
      </div>
      <div class="video-tile__actions">
        <button type="button" title="重新连接" aria-label="重新连接" @click.stop="connect"><ReloadOutlined /></button>
        <button type="button" :title="isFullscreen ? '退出全屏' : '全屏查看'" :aria-label="isFullscreen ? '退出全屏' : '全屏查看'" @click.stop="toggleFullscreen">
          <FullscreenExitOutlined v-if="isFullscreen" />
          <FullscreenOutlined v-else />
        </button>
      </div>
    </footer>

    <div v-if="status === 'connecting'" class="video-tile__center">
      <LoadingOutlined spin />
      <strong>正在建立视频连接</strong>
      <span>{{ hint }}</span>
    </div>
    <div v-else-if="status === 'error'" class="video-tile__center is-error">
      <WarningOutlined />
      <strong>画面连接失败</strong>
      <span>{{ message }}</span>
      <button type="button" @click.stop="connect">重新连接</button>
    </div>
    <div v-else-if="status === 'idle'" class="video-tile__center">
      <VideoCameraOutlined />
      <strong>画面待接入</strong>
      <span>{{ hint }}</span>
    </div>

    <span v-if="status === 'live'" class="video-tile__timestamp">{{ timestamp }}</span>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  FullscreenExitOutlined,
  FullscreenOutlined,
  LoadingOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import { resolveWhepUrl, sourceProtocolLabel } from '../utils/videoSource.js'

const props = defineProps({
  source: { type: Object, required: true },
  active: { type: Boolean, default: true },
})
const emit = defineEmits(['status'])

const tileEl = ref(null)
const videoEl = ref(null)
const status = ref('idle')
const message = ref('')
const hint = ref('')
const isFullscreen = ref(false)
const timestamp = ref('')

let pc = null
let sessionUrl = ''
let generation = 0
let disconnectedTimer
let clockTimer

const stateText = computed(() => ({ live: '实时画面', connecting: '连接中', error: '连接异常', idle: '未连接' }[status.value]))
const protocolLabel = computed(() => sourceProtocolLabel(props.source))

function nowText() {
  const date = new Date()
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).replaceAll('/', '-')
}

function setStatus(next, detail = '') {
  status.value = next
  message.value = detail
  emit('status', { id: props.source?.sourceId, status: next, message: detail })
}

function teardown() {
  if (disconnectedTimer) {
    window.clearTimeout(disconnectedTimer)
    disconnectedTimer = undefined
  }
  if (pc) {
    pc.ontrack = null
    pc.onconnectionstatechange = null
    pc.oniceconnectionstatechange = null
    try { pc.close() } catch { /* 已关闭 */ }
    pc = null
  }
  if (videoEl.value) videoEl.value.srcObject = null
  if (sessionUrl) {
    const url = sessionUrl
    sessionUrl = ''
    // WHEP 会话用完要 DELETE，否则网关会一直保留一路订阅
    fetch(url, { method: 'DELETE' }).catch(() => {})
  }
}

function waitForIce(connection) {
  return new Promise((resolve) => {
    if (connection.iceGatheringState === 'complete') return resolve()
    const timer = window.setTimeout(resolve, 2500)
    connection.addEventListener('icegatheringstatechange', () => {
      if (connection.iceGatheringState === 'complete') {
        window.clearTimeout(timer)
        resolve()
      }
    }, { once: true })
  })
}

async function connect() {
  const current = ++generation
  teardown()
  message.value = ''
  timestamp.value = nowText()

  if (!props.active) {
    hint.value = '画面已停用'
    setStatus('idle')
    return
  }
  if (typeof window === 'undefined' || !window.RTCPeerConnection) {
    hint.value = '当前浏览器不支持 WebRTC'
    setStatus('error', '请使用 Chrome / Edge 等支持 WebRTC 的浏览器')
    return
  }

  const resolved = resolveWhepUrl(props.source)
  hint.value = resolved.url || resolved.reason
  if (!resolved.url) {
    setStatus('error', resolved.reason || '未配置可播放地址')
    return
  }

  setStatus('connecting')
  const connection = new RTCPeerConnection({ iceServers: [], bundlePolicy: 'max-bundle' })
  pc = connection

  connection.ontrack = (event) => {
    if (current !== generation || !videoEl.value) return
    const stream = event.streams?.[0]
    if (stream) {
      videoEl.value.srcObject = stream
      videoEl.value.play().catch(() => { /* 等待用户交互时静默失败 */ })
    }
    setStatus('live')
  }

  connection.onconnectionstatechange = () => {
    if (current !== generation || pc !== connection) return
    const state = connection.connectionState
    if (state === 'connected') {
      setStatus('live')
    } else if (state === 'failed') {
      setStatus('error', 'WebRTC 协商失败，请检查网关、地址或证书')
    } else if (state === 'disconnected') {
      if (disconnectedTimer) window.clearTimeout(disconnectedTimer)
      disconnectedTimer = window.setTimeout(() => {
        if (current === generation && pc === connection && connection.connectionState !== 'connected') {
          setStatus('error', '视频连接已断开，请重新连接')
        }
      }, 4000)
    }
  }

  try {
    connection.addTransceiver('video', { direction: 'recvonly' })
    connection.addTransceiver('audio', { direction: 'recvonly' })
    const offer = await connection.createOffer()
    await connection.setLocalDescription(offer)
    await waitForIce(connection)
    if (current !== generation) return

    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    let response
    try {
      response = await fetch(resolved.url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp', Accept: 'application/sdp' },
        body: connection.localDescription.sdp,
        signal: controller.signal,
      })
    } finally {
      window.clearTimeout(timeout)
    }
    if (current !== generation) return

    const answer = await response.text()
    if (!response.ok) {
      const detail = (() => {
        try { return JSON.parse(answer)?.error || answer } catch { return answer }
      })()
      throw new Error(`网关返回 ${response.status}${detail ? `：${String(detail).slice(0, 80)}` : ''}`)
    }

    const location = response.headers.get('Location')
    if (location) {
      try { sessionUrl = new URL(location, resolved.url).toString() } catch { sessionUrl = '' }
    }
    await connection.setRemoteDescription({ type: 'answer', sdp: answer })
    if (current !== generation) return
    if (connection.connectionState === 'connected' || connection.iceConnectionState === 'connected' || connection.iceConnectionState === 'completed') {
      setStatus('live')
    }
  } catch (error) {
    if (current !== generation) return
    const text = error?.name === 'AbortError' ? '连接网关超时（15 秒）' : error?.message || '未知错误'
    setStatus('error', text)
    teardown()
  }
}

function toggleFullscreen() {
  const element = tileEl.value
  if (!element) return
  if (document.fullscreenElement === element) {
    document.exitFullscreen?.().catch(() => {})
  } else {
    element.requestFullscreen?.().catch(() => {})
  }
}

function syncFullscreen() {
  isFullscreen.value = document.fullscreenElement === tileEl.value
}

function formatClock() {
  timestamp.value = new Date().toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).replaceAll('/', '-')
}

watch(() => [props.active, props.source?.protocol, props.source?.sourceUrl, props.source?.playUrl, props.source?.gatewayUrl, props.source?.streamKey], () => {
  void connect()
})

onMounted(() => {
  document.addEventListener('fullscreenchange', syncFullscreen)
  formatClock()
  clockTimer = window.setInterval(formatClock, 1000)
  void connect()
})

onBeforeUnmount(() => {
  generation += 1
  document.removeEventListener('fullscreenchange', syncFullscreen)
  if (clockTimer) window.clearInterval(clockTimer)
  teardown()
})
</script>

<style scoped>
.video-tile { position: relative; min-width: 0; overflow: hidden; aspect-ratio: 16 / 9; border: 1px solid #0d2a3d; border-radius: 13px; background: radial-gradient(circle at 50% 42%, #12354a, #06121c 72%); color: #e7f6ff; box-shadow: 0 10px 26px rgba(8, 31, 49, .16); }
.video-tile__video { position: absolute; inset: 0; width: 100%; height: 100%; background: #06121c; object-fit: contain; }
.video-tile__vignette { position: absolute; inset: 0; pointer-events: none; background: linear-gradient(180deg, rgba(2, 12, 20, .55) 0%, transparent 18%, transparent 72%, rgba(2, 12, 20, .72) 100%); }
.video-tile__head { position: absolute; top: 0; left: 0; right: 0; z-index: 2; display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 10px 12px; }
.video-tile__live { display: inline-flex; align-items: center; gap: 5px; padding: 4px 8px; border-radius: 20px; background: rgba(3, 18, 28, .58); color: #9eb6c6; font-size: 9px; backdrop-filter: blur(5px); }
.video-tile__live i { width: 6px; height: 6px; border-radius: 50%; background: #7e95a6; }
.video-tile.is-live .video-tile__live { color: #d9fff2; background: rgba(6, 44, 34, .58); }
.video-tile.is-live .video-tile__live i { background: #2ee0a4; box-shadow: 0 0 0 3px rgba(46, 224, 164, .18); animation: vt-pulse 2s ease-in-out infinite; }
.video-tile.is-connecting .video-tile__live i { background: #e8b34f; box-shadow: 0 0 0 3px rgba(232, 179, 79, .16); }
.video-tile.is-error .video-tile__live { color: #ffd9d6; background: rgba(64, 15, 14, .55); }
.video-tile.is-error .video-tile__live i { background: #f1746a; }
.video-tile__protocol { padding: 4px 8px; border: 1px solid rgba(133, 190, 224, .22); border-radius: 20px; background: rgba(3, 18, 28, .46); color: #9cc4dc; font-size: 8px; letter-spacing: .04em; backdrop-filter: blur(5px); }
.video-tile__foot { position: absolute; left: 0; right: 0; bottom: 0; z-index: 2; display: flex; align-items: flex-end; justify-content: space-between; gap: 10px; padding: 0 12px 10px; }
.video-tile__meta { min-width: 0; }
.video-tile__meta strong { display: block; overflow: hidden; color: #f1fbff; font-size: 12px; font-weight: 600; text-shadow: 0 1px 5px rgba(0, 0, 0, .55); text-overflow: ellipsis; white-space: nowrap; }
.video-tile__meta small { display: block; overflow: hidden; margin-top: 2px; color: #a8c2d2; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.video-tile__actions { display: flex; gap: 5px; flex: 0 0 auto; }
.video-tile__actions button { display: inline-flex; align-items: center; justify-content: center; width: 27px; height: 27px; border: 1px solid rgba(159, 208, 234, .22); border-radius: 8px; background: rgba(4, 20, 31, .5); color: #cfe9f7; font-size: 12px; cursor: pointer; backdrop-filter: blur(5px); transition: .15s ease; }
.video-tile__actions button:hover { border-color: rgba(84, 205, 255, .65); background: rgba(16, 75, 106, .72); color: #fff; }
.video-tile__center { position: absolute; inset: 0; z-index: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 7px; padding: 20px; text-align: center; }
.video-tile__center > :deep(svg) { color: #69a8c9; font-size: 26px; }
.video-tile__center strong { color: #d5ecf8; font-size: 12px; font-weight: 500; }
.video-tile__center span { max-width: 88%; overflow: hidden; color: #82a3b6; font-size: 9px; line-height: 1.6; text-overflow: ellipsis; }
.video-tile__center.is-error > :deep(svg) { color: #ef8a80; }
.video-tile__center.is-error strong { color: #ffd7d3; }
.video-tile__center button { margin-top: 5px; padding: 5px 12px; border: 1px solid rgba(133, 190, 224, .3); border-radius: 7px; background: rgba(9, 40, 57, .7); color: #cfe9f7; font: inherit; font-size: 9px; cursor: pointer; }
.video-tile__center button:hover { border-color: #6fd1f4; color: #fff; }
.video-tile__timestamp { position: absolute; right: 12px; top: 45px; z-index: 2; color: rgba(203, 233, 247, .65); font-size: 8px; font-variant-numeric: tabular-nums; text-shadow: 0 1px 4px rgba(0, 0, 0, .6); }
.video-tile:fullscreen, .video-tile.is-fullscreen { width: 100vw; height: 100vh; aspect-ratio: auto; border: 0; border-radius: 0; background: #000; }
.video-tile:fullscreen .video-tile__video, .video-tile.is-fullscreen .video-tile__video { object-fit: contain; }
.video-tile:fullscreen .video-tile__meta strong, .video-tile.is-fullscreen .video-tile__meta strong { font-size: 15px; }
@keyframes vt-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }
</style>
