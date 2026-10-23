<template>
  <div ref="rootEl" class="twin-overlay">
    <button
      v-for="label in LABELS"
      :key="label.key"
      type="button"
      class="twin-hit"
      :style="hitStyle(label.key)"
      :aria-label="`打开${label.name}`"
      @click="open(label.key)"
    ></button>

    <div v-if="activeLabel" class="twin-pop" :style="popupStyle">
      <header class="twin-pop__head">
        <div>
          <strong>{{ activeLabel === 'drowning' ? '溺水监测点 · 实时画面' : '无人艇 · 状态' }}</strong>
          <small v-if="activeLabel === 'drowning' && drowningSource">{{ drowningSource.sourceName }} · {{ drowningSource.location || '未填写位置' }}</small>
        </div>
        <button type="button" aria-label="关闭" @click="activeLabel = null">×</button>
      </header>

      <template v-if="activeLabel === 'drowning'">
        <VideoTile v-if="drowningSource" :source="drowningSource" />
        <div v-else class="twin-pop__empty">
          <VideoCameraOutlined />
          <strong>未绑定摄像头</strong>
          <span>请管理员在「画面来源设置」中把一路画面绑定到溺水监测点。</span>
          <button v-if="canManage" type="button" @click="goCameraSettings">去绑定</button>
        </div>
      </template>

      <div class="twin-pop__status">
        <div class="twin-pop__status-head">
          <span class="twin-pop__chip" :class="`is-${activeMeta.tone}`">{{ activeMeta.text }}</span>
          <small>{{ activeMeta.time || '等待状态频道' }}</small>
        </div>
        <p>{{ activeMeta.detail || '暂无详细状态' }}</p>
      </div>
    </div>

    <div v-if="showDrowningAlert" class="twin-alert">
      <WarningOutlined />
      <div>
        <strong>发现溺水人员，请立即处置</strong>
        <span>{{ drowningMeta.detail || '溺水检测状态异常' }}</span>
      </div>
      <button type="button" @click="alertDismissed = true">知道了</button>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  VideoCameraOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import VideoTile from './VideoTile.vue'
import { getTwinAlerts, listCameraSources } from '../api/manageApi.js'

const props = defineProps({
  project: { type: Function, required: true },
  setLabelState: { type: Function, default: null },
})

const router = useRouter()
const rootEl = ref(null)
const positions = ref({})
const activeLabel = ref(null)
const alertDismissed = ref(false)
const alerts = ref({})
const sources = ref([])

const LABELS = [
  { key: 'drowning', name: '溺水监测点', anchor: [-34, 8.77, 5] },
  { key: 'boat', name: '无人艇', anchor: [-6, 8.77, -22] },
]

const canManage = computed(() => {
  const level = Number(localStorage.getItem('level') ?? 1)
  return level === 0 || level >= 3
})

const drowningSource = computed(() => sources.value.find((item) => item.twinLabel === 'drowning' && item.enabled !== 0) || null)

function formatTime(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).replaceAll('/', '-')
}

function normalize(raw) {
  const status = String(raw?.status || '').trim()
  const detail = raw?.detail || ''
  const time = formatTime(raw?.time)
  if (!status) return { tone: 'unknown', text: '未知', detail, time }
  const lower = status.toLowerCase()
  if (lower === 'normal') return { tone: 'normal', text: '正常', detail, time }
  if (lower === 'error') return { tone: 'error', text: '异常', detail, time }
  const text = lower === 'busy' ? '忙碌' : lower === 'working' ? '作业中' : status
  return { tone: 'warning', text, detail, time }
}

function metaFor(key) {
  return normalize(alerts.value[key])
}

const drowningMeta = computed(() => metaFor('drowning'))
const boatMeta = computed(() => metaFor('boat'))
const activeMeta = computed(() => metaFor(activeLabel.value))

const showDrowningAlert = computed(() => drowningMeta.value.tone === 'error' && !alertDismissed.value)

function hitStyle(key) {
  const point = positions.value[key]
  if (!point?.visible) return { display: 'none' }
  return { left: `${point.x}px`, top: `${point.y}px` }
}

const popupStyle = computed(() => {
  const point = positions.value[activeLabel.value]
  const root = rootEl.value
  if (!point || !root) return { left: '50%', top: '50%', transform: 'translate(-50%, -50%)' }
  const width = 390
  const height = 430
  let left = point.x + 24
  if (left + width > root.clientWidth - 12) left = point.x - width - 24
  left = Math.max(12, Math.min(left, root.clientWidth - width - 12))
  const top = Math.max(12, Math.min(point.y - 40, root.clientHeight - height - 12))
  return { left: `${left}px`, top: `${top}px` }
})

async function open(key) {
  const next = activeLabel.value === key ? null : key
  if (next === 'drowning') {
    await loadSources()
  }
  activeLabel.value = next
}

function goCameraSettings() {
  void router.push({ name: 'camera-sources' })
}

let raf = 0
let lastProject = 0
function tick(now) {
  if (now - lastProject > 50) {
    lastProject = now
    const next = {}
    for (const label of LABELS) {
      const point = props.project?.(label.anchor)
      if (point) next[label.key] = point
    }
    positions.value = next
  }
  raf = requestAnimationFrame(tick)
}

let pollTimer = 0
async function refreshAlerts() {
  try {
    const result = await getTwinAlerts()
    alerts.value = result.data || {}
    for (const label of LABELS) {
      const meta = metaFor(label.key)
      props.setLabelState?.(label.key, { name: label.name, status: meta.text, tone: meta.tone })
    }
  } catch {
    // 状态接口失败时保留上一帧，不把灯打回未知
  }
}

async function loadSources() {
  try {
    const result = await listCameraSources()
    sources.value = result.data || []
  } catch {
    sources.value = []
  }
}

let audioCtx = null
function playBeep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext
    if (!Ctx) return
    audioCtx = audioCtx || new Ctx()
    if (audioCtx.state === 'suspended') void audioCtx.resume()
    const osc = audioCtx.createOscillator()
    const gain = audioCtx.createGain()
    const now = audioCtx.currentTime
    osc.type = 'sine'
    osc.frequency.value = 880
    gain.gain.setValueAtTime(0.0001, now)
    gain.gain.exponentialRampToValueAtTime(0.08, now + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.5)
    osc.connect(gain)
    gain.connect(audioCtx.destination)
    osc.start(now)
    osc.stop(now + 0.55)
  } catch {
    // 浏览器限制自动播放时静默，页面红色告警条仍然可见
  }
}

watch(() => drowningMeta.value.tone, (tone, previous) => {
  if (tone === 'warning' || tone === 'error') {
    if (previous !== tone) {
      void loadSources()
      activeLabel.value = 'drowning'
    }
    if (tone === 'error' && previous !== 'error') playBeep()
  } else if (tone === 'normal' && previous && previous !== 'normal') {
    window.setTimeout(() => {
      if (drowningMeta.value.tone === 'normal' && activeLabel.value === 'drowning') activeLabel.value = null
    }, 3000)
  }
  if (tone !== 'error') alertDismissed.value = false
})

watch(() => boatMeta.value.tone, (tone, previous) => {
  if (tone === 'warning' || tone === 'error') {
    if (previous !== tone && !activeLabel.value) activeLabel.value = 'boat'
  } else if (tone === 'normal' && previous && previous !== 'normal') {
    window.setTimeout(() => {
      if (boatMeta.value.tone === 'normal' && activeLabel.value === 'boat') activeLabel.value = null
    }, 3000)
  }
})

onMounted(() => {
  void loadSources()
  void refreshAlerts()
  pollTimer = window.setInterval(refreshAlerts, 3000)
  raf = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  if (pollTimer) window.clearInterval(pollTimer)
  if (raf) cancelAnimationFrame(raf)
})

defineExpose({ open })
</script>

<style scoped>
.twin-overlay {
  position: absolute;
  inset: 0;
  z-index: 3;
  pointer-events: none;
}

.twin-hit {
  position: absolute;
  width: 300px;
  height: 120px;
  border: 0;
  background: transparent;
  opacity: 0;
  transform: translate(-50%, -50%);
  pointer-events: auto;
  cursor: pointer;
}

.twin-tag {
  position: absolute;
  display: flex;
  align-items: center;
  gap: 7px;
  min-width: 112px;
  padding: 6px 9px 6px 6px;
  border: 1px solid rgba(120, 200, 235, .28);
  border-radius: 9px;
  background: rgba(4, 24, 35, .78);
  color: #e9fbff;
  font: inherit;
  text-align: left;
  cursor: pointer;
  pointer-events: auto;
  transform: translate(-50%, -100%);
  box-shadow: 0 6px 18px rgba(0, 0, 0, .28);
  backdrop-filter: blur(6px);
}

.twin-tag::after {
  content: '';
  position: absolute;
  left: 50%;
  top: 100%;
  width: 1px;
  height: 16px;
  background: linear-gradient(rgba(126, 214, 244, .75), rgba(126, 214, 244, 0));
}

.twin-tag.is-active {
  border-color: rgba(126, 224, 255, .85);
  box-shadow: 0 0 0 1px rgba(126, 224, 255, .25), 0 8px 22px rgba(0, 0, 0, .35);
}

.twin-tag__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 25px;
  width: 25px;
  height: 25px;
  border-radius: 7px;
  background: rgba(79, 209, 255, .16);
  color: #7fe0ff;
  font-size: 13px;
}

.twin-tag__text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  line-height: 1.2;
}

.twin-tag__text strong {
  font-size: 10px;
  font-weight: 600;
  white-space: nowrap;
}

.twin-tag__text small {
  margin-top: 2px;
  color: #9dbccb;
  font-size: 8px;
}

.twin-tag__lamp {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  margin-left: 2px;
  border-radius: 50%;
  background: #8fa3b3;
  box-shadow: 0 0 0 3px rgba(143, 163, 179, .12);
}

.twin-tag__lamp.is-normal { background: #2ee0a4; box-shadow: 0 0 0 3px rgba(46, 224, 164, .16); }
.twin-tag__lamp.is-warning { background: #f2c14e; box-shadow: 0 0 0 3px rgba(242, 193, 78, .2); animation: twin-lamp 1.4s ease-in-out infinite; }
.twin-tag__lamp.is-error { background: #ff5d55; box-shadow: 0 0 0 3px rgba(255, 93, 85, .2); animation: twin-lamp .8s ease-in-out infinite; }

.twin-pop {
  position: absolute;
  z-index: 5;
  width: 390px;
  overflow: hidden;
  border: 1px solid rgba(111, 198, 232, .3);
  border-radius: 12px;
  background: rgba(5, 26, 38, .96);
  color: #e7f6ff;
  box-shadow: 0 18px 48px rgba(0, 0, 0, .45);
  pointer-events: auto;
}

.twin-pop__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  padding: 10px 12px 8px;
}

.twin-pop__head strong {
  display: block;
  font-size: 12px;
  font-weight: 600;
}

.twin-pop__head small {
  display: block;
  margin-top: 3px;
  color: #9dbccb;
  font-size: 9px;
}

.twin-pop__head > button {
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  border: 1px solid rgba(143, 196, 220, .2);
  border-radius: 6px;
  background: rgba(8, 40, 55, .7);
  color: #b9d8e7;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}

.twin-pop :deep(.video-tile) {
  border-radius: 0;
  border-left: 0;
  border-right: 0;
}

.twin-pop__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  min-height: 160px;
  padding: 20px;
  color: #9dbccb;
  text-align: center;
  background: rgba(4, 18, 27, .6);
}

.twin-pop__empty :deep(svg) { color: #69a8c9; font-size: 24px; }
.twin-pop__empty strong { color: #d5ecf8; font-size: 12px; font-weight: 500; }
.twin-pop__empty span { font-size: 9px; line-height: 1.6; }
.twin-pop__empty button { margin-top: 4px; padding: 5px 12px; border: 1px solid rgba(111, 198, 232, .35); border-radius: 6px; background: rgba(9, 40, 57, .8); color: #cfe9f7; font: inherit; font-size: 9px; cursor: pointer; }

.twin-pop__status {
  padding: 9px 12px 11px;
  border-top: 1px solid rgba(111, 198, 232, .14);
}

.twin-pop__status-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.twin-pop__status-head small {
  color: #829dac;
  font-size: 8px;
}

.twin-pop__chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 7px;
  border-radius: 5px;
  font-size: 9px;
  background: rgba(143, 163, 179, .14);
  color: #a9bdc9;
}

.twin-pop__chip.is-normal { background: rgba(46, 224, 164, .14); color: #69e6bb; }
.twin-pop__chip.is-warning { background: rgba(242, 193, 78, .15); color: #f2c14e; }
.twin-pop__chip.is-error { background: rgba(255, 93, 85, .15); color: #ff8a84; }

.twin-pop__status p {
  margin: 7px 0 0;
  color: #b9d4e2;
  font-size: 10px;
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.twin-alert {
  position: absolute;
  top: 12px;
  left: 50%;
  z-index: 6;
  display: flex;
  align-items: center;
  gap: 9px;
  max-width: min(520px, calc(100% - 24px));
  padding: 8px 10px;
  border: 1px solid rgba(255, 93, 85, .55);
  border-radius: 9px;
  background: rgba(74, 12, 12, .9);
  color: #ffe9e7;
  box-shadow: 0 10px 28px rgba(0, 0, 0, .38);
  transform: translateX(-50%);
  pointer-events: auto;
}

.twin-alert :deep(svg) { flex: 0 0 auto; color: #ff8a84; font-size: 16px; }
.twin-alert div { min-width: 0; }
.twin-alert strong { display: block; font-size: 11px; font-weight: 600; white-space: nowrap; }
.twin-alert span { display: block; overflow: hidden; margin-top: 2px; color: #ffb9b4; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.twin-alert button { flex: 0 0 auto; margin-left: 6px; padding: 4px 9px; border: 1px solid rgba(255, 185, 180, .4); border-radius: 5px; background: rgba(255, 255, 255, .08); color: #fff0ee; font: inherit; font-size: 9px; cursor: pointer; }

@keyframes twin-lamp {
  0%, 100% { opacity: 1; }
  50% { opacity: .35; }
}
</style>
