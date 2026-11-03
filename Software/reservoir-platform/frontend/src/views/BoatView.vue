<template>
  <ViewShell title="无人艇中心" tag="串口桥接 · ESP-NOW 控制链路" :icon="SendOutlined">
    <div class="boat-page">
      <section class="boat-hero">
        <div class="boat-hero__copy">
          <span class="boat-kicker">无人艇驾驶控制</span>
          <h2>{{ boatDevice?.deviceName || (boatDeviceLoading ? '正在读取设备档案…' : '当前水库未关联无人艇') }}</h2>
          <small v-if="boatDevice" class="boat-device-code">设备编码：{{ boatDevice.deviceCode || '未填写' }} · {{ boatDevice.deviceType || '无人艇' }}</small>
          <small v-else-if="boatDeviceError" class="boat-device-code is-error">{{ boatDeviceError }}</small>
          <p>控制链路为本地 WebSocket → serial-service → 串口 → ESP-NOW。页面只负责下发驾驶指令和显示船端遥测。</p>
          <div class="boat-status" :class="{ 'is-offline': !serialConnected }"><i></i>{{ serialConnected ? '串口已连接，可接管无人艇' : '串口未连接，当前仅可查看界面' }}<span>{{ selectedPort || '等待桥接板端口' }}</span></div>
          <div class="boat-hero__actions">
            <div class="boat-status is-vision" :class="{ 'is-offline': !vision.active, 'is-blocked': !vision.gate }"><i></i>{{ visionLabel }}<span>{{ visionAgeText }}</span></div>
            <button v-if="!vision.gate" type="button" class="secondary-button is-compact" @click="allowVision">恢复视觉接管</button>
            <button type="button" class="emergency-button" @click="emergencyStop">急停 <kbd>SPACE</kbd></button>
          </div>
        </div>
        <div class="boat-visual"><div class="boat-water"></div><div class="boat-route"></div><div class="boat-model">◢<small>{{ boatDevice?.deviceCode || '无人艇' }}</small></div><span class="boat-map-label label-a">航行示意</span><span class="boat-map-label label-b">控制链路示意</span></div>
      </section>

      <section class="boat-grid">
        <article class="boat-card">
          <header><h2>控制链路</h2><span class="badge" :class="serialConnected ? 'badge-green' : 'badge-gray'">{{ serialConnected ? '在线' : '离线' }}</span></header>
          <div class="serial-row"><select v-model="selectedPort" :disabled="serialConnected"><option value="">选择桥接板串口</option><option v-for="port in ports" :key="port.path" :value="port.path">{{ port.path }}{{ port.isEspressif ? ' · ESP32' : '' }}</option></select><button type="button" class="minor-button" @click="refreshPorts">刷新</button></div>
          <button v-if="!serialConnected" type="button" class="primary-button" :disabled="!selectedPort || serviceStatus === 'connecting'" @click="connectSerial">连接无人艇</button>
          <button v-else type="button" class="secondary-button" @click="disconnectSerial">断开串口</button>
          <p class="card-note">桥接板服务地址：127.0.0.1:4174 · 115200 baud</p>
        </article>
        <article class="boat-card">
          <header><h2>船端遥测</h2><span class="badge" :class="telemetryStale ? 'badge-red' : telemetry ? 'badge-green' : 'badge-gray'">{{ telemetryStale ? (telemetrySeen ? '遥测中断' : '无遥测') : telemetry ? '持续回传' : '等待数据' }}</span></header>
          <dl><div><dt>左侧电机</dt><dd>{{ telemetry ? telemetry.leftMotor : '—' }}</dd></div><div><dt>右侧电机</dt><dd>{{ telemetry ? telemetry.rightMotor : '—' }}</dd></div><div><dt>船头航向</dt><dd>{{ headingText }}</dd></div><div><dt>通信状态</dt><dd :class="{ warn: telemetryStale }">{{ commText }}</dd></div><div><dt>目标识别</dt><dd>{{ telemetry?.targetDetected ? '已锁定' : '未检测' }}</dd></div><div><dt>目标距离</dt><dd>{{ targetDistanceText }}</dd></div></dl>
          <p class="card-note is-vision">视觉下发：{{ visionNavText }}</p>
        </article>
        <article class="boat-card"><header><h2>任务状态</h2><span class="badge badge-blue">{{ missionLabel }}</span></header><ul class="boat-checks"><li><i :class="{ warn: !serialConnected }"></i>串口桥接服务 <b :class="{ warn: !serialConnected }">{{ serialConnected ? '正常' : '未连接' }}</b></li><li><i :class="{ warn: telemetryStale }"></i>遥测链路 <b :class="{ warn: telemetryStale }">{{ telemetryStale ? (telemetrySeen ? '中断 1.5s' : '无数据') : '正常' }}</b></li><li><i :class="{ warn: !vision.active && vision.gate }"></i>视觉定位接管 <b :class="{ warn: !vision.active && vision.gate }">{{ visionLabel }}</b></li><li><i :class="{ warn: telemetry?.emergency }"></i>船端安全状态 <b :class="{ warn: telemetry?.emergency }">{{ telemetry?.emergency ? '应急' : '监视中' }}</b></li><li><i :class="{ warn: videoState === 'error' }"></i>船载视频回传 <b :class="{ warn: videoState === 'error' }">{{ videoState === 'live' ? '实时中' : videoState === 'error' ? '连接异常' : '待接入' }}</b></li></ul></article>
      </section>

      <section class="boat-control-grid">
        <article class="boat-card control-card">
          <header><div><h2>驾驶控制</h2><small>WASD 按住驱动 · 松开即停</small></div><div class="header-badges"><span class="badge" :class="vision.active ? 'badge-orange' : 'badge-gray'">{{ visionLabel }}</span><span class="badge" :class="armed ? 'badge-green' : 'badge-gray'">{{ armed ? '动力已解锁' : '动力已锁定' }}</span></div></header>
          <div class="mode-switch"><button type="button" :class="{ selected: controlMode === 'manual' }" @click="changeControlMode('manual')">手动</button><button type="button" :class="{ selected: controlMode === 'autonomous' }" @click="changeControlMode('autonomous')">自主</button></div>
          <div v-if="controlMode === 'manual'" class="manual-panel">
            <div class="keypad"><span></span><button type="button" :class="{ active: pressed.forward }" @pointerdown="setDrive('forward', true)" @pointerup="setDrive('forward', false)" @pointerleave="setDrive('forward', false)">W</button><span></span><button type="button" :class="{ active: pressed.left }" @pointerdown="setDrive('left', true)" @pointerup="setDrive('left', false)" @pointerleave="setDrive('left', false)">A</button><button type="button" :class="{ active: pressed.reverse }" @pointerdown="setDrive('reverse', true)" @pointerup="setDrive('reverse', false)" @pointerleave="setDrive('reverse', false)">S</button><button type="button" :class="{ active: pressed.right }" @pointerdown="setDrive('right', true)" @pointerup="setDrive('right', false)" @pointerleave="setDrive('right', false)">D</button></div>
            <label class="power-row"><span>推进功率</span><input v-model.number="power" type="range" min="20" max="100" step="5" /><b>{{ power }}%</b></label>
          </div>
          <div v-else class="navigation-grid"><label>船 X<input v-model="navigation.boatX" inputmode="decimal" placeholder="0–1.2 m" /></label><label>船 Y<input v-model="navigation.boatY" inputmode="decimal" placeholder="0–1.2 m" /></label><label>航向<input v-model="navigation.heading" inputmode="decimal" placeholder="0–359.9°" /></label><label>目标 X<input v-model="navigation.targetX" inputmode="decimal" placeholder="0–1.2 m" /></label><label>目标 Y<input v-model="navigation.targetY" inputmode="decimal" placeholder="0–1.2 m" /></label><p>坐标全部留空时，船端进入 HUSKYLENS 视觉搜救模式；四项坐标全 0 会被船端当作“无定位”，不能用来跑坐标导航。</p></div>
          <div class="control-footer"><span><i :class="{ on: armed }"></i>{{ armed ? (controlMode === 'manual' ? '手动控制中' : '自主导航中') : '待机中' }}</span><button type="button" class="arm-button" :class="{ armed }" :disabled="!serialConnected" @click="armed ? stopDrive(true) : armDrive()">{{ armed ? '锁定动力' : serialConnected ? '解锁驾驶' : '请先连接设备' }}</button></div>
        </article>

        <article class="boat-card telemetry-card boat-stream-card">
          <header><div><h2>船载视角</h2><small>Janus WebRTC · Stream {{ STREAM_ID }}</small></div><span class="fresh-text" :class="`stream-${videoState}`">{{ videoStateText }}</span></header>
          <div ref="streamViewport" class="boat-stream-viewport">
            <video ref="boatVideo" class="boat-stream-video" autoplay playsinline muted></video>
            <div v-if="videoState !== 'live'" class="boat-stream-empty">
              <div class="stream-radar"><i></i><i></i><span></span></div>
              <strong>{{ videoStateText }}</strong>
              <small>{{ JANUS_URL }} · Stream {{ STREAM_ID }}</small>
              <button type="button" class="stream-connect-button" :disabled="videoState === 'connecting'" @click="videoState === 'idle' || videoState === 'error' ? startStream() : stopStream()">
                {{ videoState === 'connecting' ? '正在连接…' : videoState === 'error' ? '重新接入' : '接入船载视角' }}
              </button>
            </div>
            <div class="stream-overlay"><span><i :class="{ online: videoState === 'live' }"></i>{{ videoState === 'live' ? 'LIVE · 船载视角' : '船载视角' }}</span><span>Janus WebRTC</span></div>
            <div v-if="videoState === 'live'" class="stream-bottom"><span>WEBRTC · {{ STREAM_ID }}</span><div><button type="button" @click="stopStream">断开</button><button type="button" @click="toggleStreamFullscreen">全屏</button></div></div>
          </div>
          <div class="telemetry-line"><span>船头航向</span><strong>{{ headingText }}</strong><span>推进输出</span><strong>{{ propulsionText }}</strong></div>
          <div class="release-row"><button type="button" class="release-button" :disabled="!serialConnected" @click="triggerRelease">{{ releaseConfirm ? '再次点击确认投放' : '投放释放' }}</button><span class="release-state" :class="{ 'is-sent': releaseSentAt }">{{ releaseSentAt ? '已下发' : '待命' }}</span></div>
          <small class="release-note">投放会强制停船并通过串口桥接服务下发，属于不可逆动作；舵机拉出插销保持 500 ms 后自动回位。</small>
        </article>
      </section>
    </div>
    <p v-if="serviceError" class="boat-error">{{ serviceError }}</p>
  </ViewShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { SendOutlined } from '@ant-design/icons-vue'
import Janus from 'janus-gateway'
import adapterPackage from 'webrtc-adapter'
import ViewShell from './ViewShell.vue'
import { BoatControlService } from '../utils/boatControlService.js'
import { JANUS_STREAM_ID as STREAM_ID, JANUS_URL } from '../utils/boatConfig.js'
import { listDevices } from '../api/manageApi.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'

globalThis.adapter = adapterPackage?.default ?? adapterPackage

// 与 serial-service / 固件保持一致的量程与超时
const POOL_SIZE_M = 1.2
const HEADING_MAX = 359.9
const TELEMETRY_TIMEOUT_MS = 1500
const RELEASE_STATUS_MS = 6000

const serviceStatus = ref('closed')
const serialConnected = ref(false)
const ports = ref([])
const selectedPort = ref('')
const telemetry = ref(null)
const telemetryStale = ref(false)
// 是否已经收到过至少一帧遥测：用来区分"刚连上还没出数据"和"运行中断了"
const telemetrySeen = ref(false)
const serviceError = ref('')
const boatDevice = ref(null)
const boatDeviceLoading = ref(true)
const boatDeviceError = ref('')
const { selectedDamId, loadDams } = useCurrentDam()
const controlMode = ref('manual')
const armed = ref(false)
const power = ref(55)
const pressed = reactive({ forward: false, reverse: false, left: false, right: false })
const navigation = reactive({ boatX: '', boatY: '', heading: '', targetX: '', targetY: '' })
// 视觉通道：locator.py 通过本地服务接管时，页面必须看得见谁在控制船
const vision = reactive({ gate: true, active: false, ageMs: null, navigation: null })
const boatVideo = ref(null)
const streamViewport = ref(null)
const videoState = ref('idle')
const janus = ref(null)
const streamHandle = ref(null)
const releaseConfirm = ref(false)
const releaseSentAt = ref(null)
let releaseTimer
let releaseStatusTimer
let commandTimer
let streamTimer
let telemetryTimer
let boatDeviceRequest = 0
let boatService

const missionLabel = computed(() => {
  if (!serialConnected.value) return '未连接'
  if (telemetry.value?.emergency) return '船端应急'
  if (!armed.value) return '待命'
  return controlMode.value === 'manual' ? '手动控制' : '自主航行'
})
const visionLabel = computed(() => (vision.active ? '视觉接管中' : vision.gate ? '视觉待机' : '视觉已屏蔽'))
const visionAgeText = computed(() => {
  // 服务端会保留最后一条视觉坐标；超过 5 秒没更新就认为没在推送，别显示一个越来越大的毫秒数
  if (!vision.active && (vision.ageMs === null || vision.ageMs > 5000)) return '视觉未推送'
  return Number.isFinite(vision.ageMs) ? `视觉数据 ${Math.round(vision.ageMs)} ms 前` : '视觉未推送'
})
const visionNavText = computed(() => {
  const nav = vision.navigation
  if (!nav) return '—'
  const fmt = (value) => (Number.isFinite(Number(value)) ? Number(value).toFixed(2) : '—')
  return `船 (${fmt(nav.boatX)}, ${fmt(nav.boatY)}) → 目标 (${fmt(nav.targetX)}, ${fmt(nav.targetY)})`
})
const videoStateText = computed(() => ({ idle: '船载画面待接入', connecting: '正在建立 WebRTC 连接', live: '船载画面实时中', error: '视频连接异常' }[videoState.value]))
const headingText = computed(() => {
  const value = telemetry.value?.heading
  return Number.isFinite(value) && value >= 0 && value <= 360 ? `${Math.round(value).toString().padStart(3, '0')}°` : '---°'
})
const propulsionText = computed(() => telemetry.value ? `${Math.round((Math.abs(telemetry.value.leftMotor || 0) + Math.abs(telemetry.value.rightMotor || 0)) / 4)}%` : '—')
const commText = computed(() => {
  if (telemetryStale.value) return telemetrySeen.value ? '中断' : '无数据'
  return serialConnected.value ? '稳定' : '离线'
})
const targetDistanceText = computed(() => {
  const detected = telemetry.value?.targetDetected
  const distance = Number(telemetry.value?.distance)
  return detected && Number.isFinite(distance) ? `${distance.toFixed(2)} m` : '—'
})

/** 每收到一帧遥测就重置看门狗；超时后自动锁定网页动力并提示。 */
function markTelemetry() {
  telemetryStale.value = false
  window.clearTimeout(telemetryTimer)
  telemetryTimer = window.setTimeout(() => {
    telemetryStale.value = true
    // 只提示、不自动解除解锁：船端本身有 3s 通信超时保护会自行停车，
    // 网页端强行 lock 会让"有串口、暂时收不到遥测"的台架调试没法进行。
    serviceError.value = telemetrySeen.value
      ? '遥测中断：1.5 秒没收到船端数据（桥接板/船端可能断电或超出射频范围）。船端会在 3 秒无指令后自行停车；请检查桥接板供电与射频距离'
      : '船端无遥测：串口已连但 1.5 秒内没有数据。请确认桥接板已上电、船端已开机，且两者在同一信道'
  }, TELEMETRY_TIMEOUT_MS)
}

function clearTelemetryWatch() {
  window.clearTimeout(telemetryTimer)
  telemetryTimer = undefined
  telemetryStale.value = false
}

function applyVisionState(payload) {
  if (!payload) return
  if (typeof payload.gate === 'boolean') vision.gate = payload.gate
  if (typeof payload.active === 'boolean') vision.active = payload.active
  if ('ageMs' in payload) vision.ageMs = payload.ageMs
  if ('navigation' in payload) vision.navigation = payload.navigation
}

function handleMessage(message) {
  if (message.type === 'connection') {
    serialConnected.value = Boolean(message.connected)
    if (message.port) selectedPort.value = message.port
    applyVisionState(message.vision)
    if (serialConnected.value) {
      // 刚连上：先给 1.5s 等第一帧，期间不计入"超时"
      telemetrySeen.value = false
      markTelemetry()
    } else { clearTelemetryWatch(); telemetrySeen.value = false; stopDrive(false) }
  } else if (message.type === 'telemetry') {
    telemetry.value = message.telemetry
    telemetrySeen.value = true
    markTelemetry()
  } else if (message.type === 'vision') {
    applyVisionState(message)
  } else if (message.type === 'error') {
    serviceError.value = message.message || '无人艇服务异常'
  } else if (message.type === 'release') {
    releaseConfirm.value = false
    releaseSentAt.value = Date.now()
    window.clearTimeout(releaseStatusTimer)
    releaseStatusTimer = window.setTimeout(() => { releaseSentAt.value = null }, RELEASE_STATUS_MS)
  }
}

async function refreshPorts() {
  serviceError.value = ''
  try {
    ports.value = await boatService.listPorts()
    const esp = ports.value.filter((port) => port.isEspressif)
    if (!selectedPort.value && esp.length === 1) selectedPort.value = esp[0].path
    if (!selectedPort.value && ports.value.length === 1) selectedPort.value = ports.value[0].path
  } catch (error) { serviceError.value = error.message || '本地无人艇服务未启动' }
}

async function connectSerial() {
  if (!selectedPort.value) return
  serviceError.value = ''
  try { await boatService.connectSerial(selectedPort.value); serialConnected.value = true } catch (error) { serviceError.value = error.message || '串口连接失败' }
}

async function disconnectSerial() {
  stopDrive(true)
  await boatService.disconnectSerial()
  serialConnected.value = false
}

function isAllZero(nav) {
  return [nav.boatX, nav.boatY, nav.targetX, nav.targetY].every((value) => Number(value) === 0)
}

/** 全部留空 -> null（纯二哈搜救）；填写不完整/越界/全 0 -> undefined（不允许下发） */
function currentNavigation() {
  const values = Object.values(navigation)
  if (values.every((value) => value === '')) return null
  const numeric = Object.fromEntries(Object.entries(navigation).map(([key, value]) => [key, Number(value)]))
  const valid = Object.values(numeric).every(Number.isFinite)
    && !isAllZero(numeric)
    && [numeric.boatX, numeric.boatY, numeric.targetX, numeric.targetY].every((value) => value >= 0 && value <= POOL_SIZE_M)
    && numeric.heading >= 0 && numeric.heading <= HEADING_MAX
  return valid ? numeric : undefined
}

function armDrive() {
  if (!serialConnected.value) return
  const nav = currentNavigation()
  if (controlMode.value === 'autonomous' && nav === undefined) {
    const allZero = Object.values(navigation).every((value) => value !== '' && Number(value) === 0)
    serviceError.value = allZero
      ? '坐标不能全为 0：船端会把全 0 当作“没有定位”并切到二哈搜救。想走搜救请把坐标清空。'
      : `坐标请全部留空，或填写完整合法的 X/Y（0–${POOL_SIZE_M} m）与航向（0–${HEADING_MAX}°）`
    return
  }
  armed.value = true
  // 没有遥测也允许解锁（台架调试常这么用），但要明确告知：看不到船端反馈
  serviceError.value = telemetryStale.value
    ? (telemetrySeen.value
        ? '已解锁，但遥测中断：看不到船端电机/应急状态，操作请谨慎'
        : '已解锁，但还没收到船端遥测：看不到电机/应急状态，操作请谨慎')
    : ''
}

/**
 * 停止 / 锁定动力。
 *
 * lockVision=true 用于明确的急停动作（空格、ESC、急停按钮、锁定动力、断开串口）：
 * 除了归零网页通道，还会关闭服务端的「视觉接管闸门」——否则 locator.py 在跑时，
 * 网页发出的 armed:false 会被服务端用强制 armed:true 的视觉帧覆盖，急停按了船还在跑。
 * 失焦 / 切模式只归零网页通道，不切断正在执行的视觉救援。
 */
function stopDrive(lockVision = true) {
  clearPressed()
  armed.value = false
  boatService?.sendCommand({ armed: false, mode: 'manual', throttle: 0, steer: 0, navigation: null })
  if (lockVision) {
    const sent = boatService?.sendVisionGate(false)
    if (sent) { vision.gate = false; vision.active = false }
  }
}

function emergencyStop() {
  stopDrive(true)
  serviceError.value = '急停已触发：动力输出归零，视觉接管已切断'
}

function allowVision() {
  serviceError.value = ''
  if (boatService?.sendVisionGate(true)) vision.gate = true
}

function changeControlMode(mode) {
  stopDrive(false)
  controlMode.value = mode
  serviceError.value = ''
}

function setDrive(key, value) {
  if (armed.value && controlMode.value === 'manual') pressed[key] = value
}

function updateCommand() {
  const throttle = (pressed.forward ? 1 : 0) - (pressed.reverse ? 1 : 0)
  // 符号约定与固件/视觉一致：正 steer = 右转（固件 left = throttle + steer）
  const steer = (pressed.right ? 1 : 0) - (pressed.left ? 1 : 0)
  const nav = controlMode.value === 'autonomous' ? currentNavigation() : null
  boatService?.sendCommand({
    armed: armed.value && nav !== undefined,
    mode: controlMode.value,
    throttle: controlMode.value === 'manual' ? throttle * power.value * 2 : 0,
    steer: controlMode.value === 'manual' ? steer * power.value * 2 : 0,
    navigation: nav === undefined ? null : nav,
  })
}

function triggerRelease() {
  if (!serialConnected.value) return
  if (!releaseConfirm.value) {
    releaseConfirm.value = true
    window.clearTimeout(releaseTimer)
    releaseTimer = window.setTimeout(() => { releaseConfirm.value = false }, 3000)
    return
  }
  window.clearTimeout(releaseTimer)
  releaseConfirm.value = false
  boatService.release()
}

function isTyping() {
  return ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)
}

function onKeyDown(event) {
  const key = event.key.toLowerCase()
  // ESC 始终急停；空格只在非输入状态下急停，避免在坐标框里按空格误触发
  if (event.key === 'Escape' || (event.key === ' ' && !isTyping())) {
    event.preventDefault()
    emergencyStop()
    return
  }
  const map = { w: 'forward', a: 'left', s: 'reverse', d: 'right' }
  if (map[key] && !isTyping()) {
    event.preventDefault()
    setDrive(map[key], true)
  }
}

function onKeyUp(event) {
  const map = { w: 'forward', a: 'left', s: 'reverse', d: 'right' }
  const state = map[event.key.toLowerCase()]
  if (state) setDrive(state, false)
}

function clearPressed() {
  Object.keys(pressed).forEach((key) => { pressed[key] = false })
}

function onWindowBlur() {
  // 失焦只停网页通道，不切断视觉救援（要中断请用急停）
  clearPressed()
  stopDrive(false)
}

function onVisibilityChange() {
  // 切标签页/最小化时 keyup 可能收不到，必须主动清零
  if (document.visibilityState === 'hidden') {
    clearPressed()
    stopDrive(false)
  }
}

function onPointerUpAnywhere() {
  // pointerup 落在按钮外（例如按住后拖出窗口）时，pointerleave 未必触发
  clearPressed()
}

function startStream() {
  if (videoState.value === 'connecting' || videoState.value === 'live') return
  videoState.value = 'connecting'
  serviceError.value = ''
  window.clearTimeout(streamTimer)
  streamTimer = window.setTimeout(() => {
    if (videoState.value === 'connecting') {
      videoState.value = 'error'
      serviceError.value = `Janus 视频连接超时，请检查 ${JANUS_URL} 是否可达`
      janus.value?.destroy()
      janus.value = null
      streamHandle.value = null
    }
  }, 8000)
  Janus.init({ debug: false, callback: () => {
    if (!Janus.isWebrtcSupported()) { videoState.value = 'error'; serviceError.value = '当前浏览器不支持 WebRTC'; return }
    const instance = new Janus({
      server: [JANUS_URL],
      iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
      success: () => instance.attach({
        plugin: 'janus.plugin.streaming',
        success: (handle) => { streamHandle.value = handle; handle.send({ message: { request: 'watch', id: STREAM_ID } }) },
        onmessage: (_message, jsep) => {
          if (!jsep) return
          streamHandle.value?.createAnswer({
            jsep,
            media: { audioSend: false, videoSend: false },
            success: (answer) => streamHandle.value?.send({ message: { request: 'start' }, jsep: answer }),
            error: (cause) => { videoState.value = 'error'; serviceError.value = `WebRTC 协商失败：${cause}` },
          })
        },
        onremotetrack: (track, _mid, on) => {
          if (!on || track.kind !== 'video') return
          if (boatVideo.value) { boatVideo.value.srcObject = new MediaStream([track]); boatVideo.value.play().catch(() => {}) }
          window.clearTimeout(streamTimer)
          videoState.value = 'live'
        },
        oncleanup: () => { if (boatVideo.value) boatVideo.value.srcObject = null; videoState.value = 'idle' },
        error: (cause) => { videoState.value = 'error'; serviceError.value = `视频插件连接失败：${cause}` },
      }),
      error: (cause) => { videoState.value = 'error'; serviceError.value = `Janus 连接失败：${cause}` },
      destroyed: () => { videoState.value = 'idle' },
    })
    janus.value = instance
  } })
}

function stopStream() {
  window.clearTimeout(streamTimer)
  streamHandle.value?.send({ message: { request: 'stop' } })
  janus.value?.destroy()
  janus.value = null
  streamHandle.value = null
  if (boatVideo.value) boatVideo.value.srcObject = null
  videoState.value = 'idle'
}

function toggleStreamFullscreen() {
  if (!document.fullscreenElement) streamViewport.value?.requestFullscreen?.()
  else document.exitFullscreen?.()
}

async function loadBoatDevice() {
  const requestId = ++boatDeviceRequest
  boatDeviceLoading.value = true
  boatDeviceError.value = ''
  try {
    await loadDams()
    const result = await listDevices()
    if (requestId !== boatDeviceRequest) return
    boatDevice.value = (result.data || []).find((device) => String(device.damId) === String(selectedDamId.value)
      && (String(device.deviceType || '').includes('无人艇') || String(device.deviceName || '').includes('艇'))) || null
  } catch (error) { if (requestId === boatDeviceRequest) boatDeviceError.value = error.message || '设备档案读取失败' }
  finally { if (requestId === boatDeviceRequest) boatDeviceLoading.value = false }
}

watch(selectedDamId, () => { void loadBoatDevice() })

onMounted(() => {
  void loadBoatDevice()
  boatService = new BoatControlService({ onMessage: handleMessage, onStatus: (status) => { serviceStatus.value = status } })
  boatService.connect()
  void refreshPorts()
  commandTimer = window.setInterval(updateCommand, 50)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('blur', onWindowBlur)
  window.addEventListener('pointerup', onPointerUpAnywhere)
  window.addEventListener('pointercancel', onPointerUpAnywhere)
  document.addEventListener('visibilitychange', onVisibilityChange)
})

onBeforeUnmount(() => {
  window.clearInterval(commandTimer)
  window.clearTimeout(releaseTimer)
  window.clearTimeout(releaseStatusTimer)
  window.clearTimeout(streamTimer)
  window.clearTimeout(telemetryTimer)
  stopDrive(false)
  stopStream()
  boatService?.close()
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
  window.removeEventListener('blur', onWindowBlur)
  window.removeEventListener('pointerup', onPointerUpAnywhere)
  window.removeEventListener('pointercancel', onPointerUpAnywhere)
  document.removeEventListener('visibilitychange', onVisibilityChange)
})
</script>

<style scoped src="./BoatView.css"></style>
