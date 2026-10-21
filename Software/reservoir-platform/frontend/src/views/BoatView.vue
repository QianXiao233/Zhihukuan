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
        <article class="boat-card"><header><h2>船端遥测</h2><span class="badge" :class="telemetry ? 'badge-green' : 'badge-gray'">{{ telemetry ? '持续回传' : '等待数据' }}</span></header><dl><div><dt>左侧电机</dt><dd>{{ telemetry ? telemetry.leftMotor : '—' }}</dd></div><div><dt>右侧电机</dt><dd>{{ telemetry ? telemetry.rightMotor : '—' }}</dd></div><div><dt>目标识别</dt><dd>{{ telemetry?.targetDetected ? '已锁定' : '未检测' }}</dd></div><div><dt>目标距离</dt><dd>{{ telemetry?.targetDetected ? `${Number(telemetry.distance).toFixed(2)} m` : '—' }}</dd></div></dl></article>
        <article class="boat-card"><header><h2>任务状态</h2><span class="badge badge-blue">{{ missionLabel }}</span></header><ul class="boat-checks"><li><i :class="{ warn: !serialConnected }"></i>串口桥接服务 <b :class="{ warn: !serialConnected }">{{ serialConnected ? '正常' : '未连接' }}</b></li><li><i :class="{ warn: telemetry?.emergency }"></i>船端安全状态 <b :class="{ warn: telemetry?.emergency }">{{ telemetry?.emergency ? '应急' : '监视中' }}</b></li><li><i></i>HUSKYLENS 目标识别 <b>{{ telemetry?.targetDetected ? '已锁定' : '待识别' }}</b></li><li><i :class="{ warn: videoState === 'error' }"></i>船载视频回传 <b :class="{ warn: videoState === 'error' }">{{ videoState === 'live' ? '实时中' : videoState === 'error' ? '连接异常' : '待接入' }}</b></li></ul></article>
      </section>

      <section class="boat-control-grid">
        <article class="boat-card control-card">
          <header><div><h2>驾驶控制</h2><small>WASD 按住驱动 · 松开即停</small></div><span class="badge" :class="armed ? 'badge-green' : 'badge-gray'">{{ armed ? '动力已解锁' : '动力已锁定' }}</span></header>
          <div class="mode-switch"><button type="button" :class="{ selected: controlMode === 'manual' }" @click="changeControlMode('manual')">手动</button><button type="button" :class="{ selected: controlMode === 'autonomous' }" @click="changeControlMode('autonomous')">自主</button></div>
          <div v-if="controlMode === 'manual'" class="keypad"><span></span><button type="button" :class="{ active: pressed.forward }" @pointerdown="setDrive('forward', true)" @pointerup="setDrive('forward', false)" @pointerleave="setDrive('forward', false)">W</button><span></span><button type="button" :class="{ active: pressed.left }" @pointerdown="setDrive('left', true)" @pointerup="setDrive('left', false)" @pointerleave="setDrive('left', false)">A</button><button type="button" :class="{ active: pressed.reverse }" @pointerdown="setDrive('reverse', true)" @pointerup="setDrive('reverse', false)" @pointerleave="setDrive('reverse', false)">S</button><button type="button" :class="{ active: pressed.right }" @pointerdown="setDrive('right', true)" @pointerup="setDrive('right', false)" @pointerleave="setDrive('right', false)">D</button></div>
          <div v-else class="navigation-grid"><label>船 X<input v-model="navigation.boatX" inputmode="decimal" placeholder="0–1.2 m" /></label><label>船 Y<input v-model="navigation.boatY" inputmode="decimal" placeholder="0–1.2 m" /></label><label>航向<input v-model="navigation.heading" inputmode="decimal" placeholder="0–360°" /></label><label>目标 X<input v-model="navigation.targetX" inputmode="decimal" placeholder="0–1.2 m" /></label><label>目标 Y<input v-model="navigation.targetY" inputmode="decimal" placeholder="0–1.2 m" /></label><p>坐标全部留空时，船端进入 HUSKYLENS 视觉搜救模式。</p></div>
          <div class="control-footer"><span><i :class="{ on: armed }"></i>{{ armed ? (controlMode === 'manual' ? '手动控制中' : '自主导航中') : '待机中' }}</span><button type="button" class="arm-button" :class="{ armed }" :disabled="!serialConnected" @click="armed ? stopDrive() : armDrive()">{{ armed ? '锁定动力' : serialConnected ? '解锁驾驶' : '请先连接设备' }}</button></div>
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
          <div class="telemetry-line"><span>船头航向</span><strong>{{ headingText }}</strong><span>推进输出</span><strong>{{ propulsionText }}</strong></div><button type="button" class="release-button" :disabled="!serialConnected" @click="triggerRelease">{{ releaseConfirm ? '再次点击确认投放' : '投放释放' }}</button><small class="release-note">投放会强制停船并通过串口桥接服务下发，属于不可逆动作。</small>
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

const serviceStatus = ref('closed')
const serialConnected = ref(false)
const ports = ref([])
const selectedPort = ref('')
const telemetry = ref(null)
const serviceError = ref('')
const boatDevice = ref(null)
const boatDeviceLoading = ref(true)
const boatDeviceError = ref('')
const { selectedDamId, loadDams } = useCurrentDam()
const controlMode = ref('manual')
const armed = ref(false)
const pressed = reactive({ forward: false, reverse: false, left: false, right: false })
const navigation = reactive({ boatX: '', boatY: '', heading: '', targetX: '', targetY: '' })
const boatVideo = ref(null)
const streamViewport = ref(null)
const videoState = ref('idle')
const janus = ref(null)
const streamHandle = ref(null)
const releaseConfirm = ref(false)
let releaseTimer
let commandTimer
let streamTimer
let boatDeviceRequest = 0
let boatService

const missionLabel = computed(() => {
  if (!serialConnected.value) return '未连接'
  if (telemetry.value?.emergency) return '船端应急'
  if (!armed.value) return '待命'
  return controlMode.value === 'manual' ? '手动控制' : '自主航行'
})
const videoStateText = computed(() => ({ idle: '船载画面待接入', connecting: '正在建立 WebRTC 连接', live: '船载画面实时中', error: '视频连接异常' }[videoState.value]))
const headingText = computed(() => {
  const value = telemetry.value?.heading
  return Number.isFinite(value) && value >= 0 && value <= 360 ? `${Math.round(value).toString().padStart(3, '0')}°` : '---°'
})
const propulsionText = computed(() => telemetry.value ? `${Math.round((Math.abs(telemetry.value.leftMotor || 0) + Math.abs(telemetry.value.rightMotor || 0)) / 4)}%` : '—')

function handleMessage(message) {
  if (message.type === 'connection') {
    serialConnected.value = Boolean(message.connected)
    if (message.port) selectedPort.value = message.port
    if (!serialConnected.value) stopDrive()
  } else if (message.type === 'telemetry') telemetry.value = message.telemetry
  else if (message.type === 'error') serviceError.value = message.message || '无人艇服务异常'
  else if (message.type === 'release') releaseConfirm.value = false
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
  stopDrive()
  await boatService.disconnectSerial()
  serialConnected.value = false
}

function currentNavigation() {
  const values = Object.values(navigation)
  if (values.every((value) => value === '')) return null
  const numeric = Object.fromEntries(Object.entries(navigation).map(([key, value]) => [key, Number(value)]))
  const valid = Object.values(numeric).every(Number.isFinite) && [numeric.boatX, numeric.boatY, numeric.targetX, numeric.targetY].every((value) => value >= 0 && value <= 1.2) && numeric.heading >= 0 && numeric.heading < 360
  return valid ? numeric : undefined
}

function armDrive() {
  if (!serialConnected.value) return
  if (controlMode.value === 'autonomous' && currentNavigation() === undefined) { serviceError.value = '坐标请全部留空，或填写完整合法的 X/Y（0–1.2 m）与航向（0–360°）'; return }
  serviceError.value = ''
  armed.value = true
}

function stopDrive(lock = true) {
  Object.keys(pressed).forEach((key) => { pressed[key] = false })
  if (lock) armed.value = false
  boatService?.sendCommand({ armed: false, mode: 'manual', throttle: 0, steer: 0, navigation: null })
}

function changeControlMode(mode) { stopDrive(); controlMode.value = mode; serviceError.value = '' }
function setDrive(key, value) { if (armed.value && controlMode.value === 'manual') pressed[key] = value }
function updateCommand() {
  const throttle = (pressed.forward ? 1 : 0) - (pressed.reverse ? 1 : 0)
  const steer = (pressed.left ? 1 : 0) - (pressed.right ? 1 : 0)
  const nav = controlMode.value === 'autonomous' ? currentNavigation() : null
  boatService?.sendCommand({ armed: armed.value && nav !== undefined, mode: controlMode.value, throttle: controlMode.value === 'manual' ? throttle * 110 : 0, steer: controlMode.value === 'manual' ? steer * 110 : 0, navigation: nav === undefined ? null : nav })
}
function triggerRelease() {
  if (!serialConnected.value) return
  if (!releaseConfirm.value) { releaseConfirm.value = true; clearTimeout(releaseTimer); releaseTimer = window.setTimeout(() => { releaseConfirm.value = false }, 3000); return }
  clearTimeout(releaseTimer); releaseConfirm.value = false; boatService.release()
}
function onKeyDown(event) { if (event.key === ' ' || event.key === 'Escape') { event.preventDefault(); stopDrive() }; const map = { w: 'forward', a: 'left', s: 'reverse', d: 'right' }; const key = map[event.key.toLowerCase()]; if (key && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'SELECT') { event.preventDefault(); setDrive(key, true) } }
function onKeyUp(event) { const map = { w: 'forward', a: 'left', s: 'reverse', d: 'right' }; const key = map[event.key.toLowerCase()]; if (key) setDrive(key, false) }
function startStream() {
  if (videoState.value === 'connecting' || videoState.value === 'live') return
  videoState.value = 'connecting'
  serviceError.value = ''
  clearTimeout(streamTimer)
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
          clearTimeout(streamTimer)
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
  clearTimeout(streamTimer)
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
  refreshPorts()
  commandTimer = window.setInterval(updateCommand, 50)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('blur', () => stopDrive())
})
onBeforeUnmount(() => { clearInterval(commandTimer); clearTimeout(releaseTimer); clearTimeout(streamTimer); stopDrive(); stopStream(); boatService?.close(); window.removeEventListener('keydown', onKeyDown); window.removeEventListener('keyup', onKeyUp) })
</script>

<style scoped>
.boat-page{display:flex;flex-direction:column;gap:15px;min-width:920px}.boat-hero,.boat-card{border:1px solid #e2ebf3;border-radius:15px;background:#fff;box-shadow:0 8px 22px rgba(31,80,117,.06)}.boat-hero{display:grid;grid-template-columns:.9fr 1.35fr;min-height:285px;overflow:hidden}.boat-hero__copy{padding:32px}.boat-kicker{color:#2589d8;font-size:11px;letter-spacing:.12em}.boat-hero h2{margin:14px 0 6px;color:#173b59;font-size:25px}.boat-device-code{display:block;color:#839aab;font-size:10px}.boat-device-code.is-error{color:#bd5b52}.boat-hero p{max-width:390px;color:#71879b;font-size:13px;line-height:1.8}.boat-status{display:inline-flex;align-items:center;gap:7px;margin-top:30px;padding:8px 12px;border-radius:9px;background:#eafaf4;color:#168b69;font-size:11px}.boat-status.is-offline{background:#f1f4f6;color:#718291}.boat-status i{width:7px;height:7px;border-radius:50%;background:#27c499}.boat-status.is-offline i{background:#9aaab5}.boat-status span{margin-left:5px;color:#71978a}.boat-visual{position:relative;overflow:hidden;background:linear-gradient(155deg,#b8e6e6,#6cc9d3 52%,#247fae)}.boat-visual:before,.boat-visual:after{content:'';position:absolute;inset:20% -10% auto;height:1px;background:rgba(255,255,255,.4);transform:rotate(-18deg);box-shadow:0 35px rgba(255,255,255,.25),0 70px rgba(255,255,255,.2),0 105px rgba(255,255,255,.18)}.boat-visual:after{top:58%;transform:rotate(16deg);opacity:.5}.boat-water{position:absolute;inset:0;background:radial-gradient(ellipse at 65% 35%,rgba(255,255,255,.35),transparent 28%),linear-gradient(135deg,transparent 58%,rgba(20,91,129,.3) 59% 61%,transparent 62%)}.boat-route{position:absolute;left:18%;top:57%;width:58%;height:34%;border:2px dashed rgba(227,255,255,.8);border-left-color:transparent;border-radius:50%;transform:rotate(-12deg)}.boat-model{position:absolute;left:54%;top:45%;display:flex;align-items:center;justify-content:center;width:54px;height:38px;border-radius:50% 50% 45% 45%;background:#f7ffff;color:#1c97be;font-size:22px;box-shadow:0 5px 15px rgba(12,74,103,.3);transform:rotate(-14deg)}.boat-model small{position:absolute;top:42px;color:#fff;font-size:10px;white-space:nowrap}.boat-map-label{position:absolute;padding:5px 8px;border:1px solid rgba(255,255,255,.55);border-radius:6px;background:rgba(8,81,112,.45);color:#fff;font-size:10px}.label-a{left:20%;top:24%}.label-b{right:13%;bottom:20%}.boat-grid,.boat-control-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}.boat-control-grid{grid-template-columns:1.2fr 1fr}.boat-card{padding:18px}.boat-card header{display:flex;align-items:center;justify-content:space-between;margin-bottom:15px}.boat-card h2{margin:0;color:#1c405d;font-size:14px}.boat-card header small,.fresh-text{color:#91a2b0;font-size:10px}.badge{padding:4px 8px;border-radius:9px;font-size:9px}.badge-blue{color:#247ec8;background:#eaf5ff}.badge-green{color:#168b69;background:#e9faf3}.badge-gray{color:#7a8d9d;background:#edf2f5}.boat-card dl{display:grid;grid-template-columns:1fr 1fr;gap:15px 12px}.boat-card dt{color:#94a6b4;font-size:10px}.boat-card dd{margin:4px 0 0;color:#3b607a;font-size:14px;font-weight:650}.boat-checks{display:flex;flex-direction:column;gap:12px;margin:0;padding:0;list-style:none;color:#607b90;font-size:11px}.boat-checks li{display:flex;align-items:center;gap:8px}.boat-checks i{width:7px;height:7px;border-radius:50%;background:#27c499}.boat-checks i.warn{background:#e5a73f}.boat-checks b{margin-left:auto;color:#1a9c77;font-size:10px;font-weight:500}.boat-checks b.warn{color:#c68a2f}.serial-row{display:flex;gap:7px;margin-bottom:10px}.serial-row select{min-width:0;flex:1;height:31px;padding:0 8px;border:1px solid #dbe7ef;border-radius:7px;background:#fbfdfe;color:#5a7388;font-size:10px}.minor-button,.primary-button,.secondary-button,.arm-button,.release-button{border:0;border-radius:7px;font-size:10px;cursor:pointer}.minor-button{padding:0 10px;border:1px solid #d8e7f0;background:#f6fbfd;color:#3d89b4}.primary-button,.secondary-button{width:100%;height:31px}.primary-button,.arm-button.armed{background:#1686dc;color:#fff}.secondary-button{border:1px solid #d6e4ec;background:#fff;color:#607b90}.primary-button:disabled,.arm-button:disabled,.release-button:disabled{cursor:not-allowed;opacity:.55}.card-note{margin:11px 0 0;color:#93a5b3;font-size:9px;line-height:1.5}.mode-switch{display:flex;gap:6px;margin-bottom:13px}.mode-switch button{flex:1;height:29px;border:1px solid #dbe8ef;border-radius:7px;background:#f8fbfd;color:#71889b;font-size:10px;cursor:pointer}.mode-switch button.selected{border-color:#afd6ef;background:#eaf6fd;color:#1e83c5}.keypad{display:grid;grid-template-columns:repeat(3,44px);justify-content:center;gap:6px;margin:4px 0 13px}.keypad button{height:38px;border:1px solid #d6e7f0;border-radius:8px;background:#f7fbfd;color:#42738f;font-size:12px;cursor:pointer}.keypad button.active{border-color:#28a8e8;background:#e5f6ff;color:#1b87be;box-shadow:0 0 0 3px rgba(44,164,225,.12)}.navigation-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-bottom:12px}.navigation-grid label{color:#7e94a5;font-size:9px}.navigation-grid input{display:block;width:100%;height:27px;margin-top:4px;padding:0 6px;border:1px solid #dbe7ef;border-radius:6px;color:#41657b;font-size:10px}.navigation-grid p{grid-column:1/-1;margin:3px 0 0;color:#94a5b2;font-size:9px;line-height:1.5}.control-footer{display:flex;align-items:center;gap:9px}.control-footer>span{display:flex;align-items:center;gap:6px;color:#7f95a5;font-size:10px}.control-footer i{width:7px;height:7px;border-radius:50%;background:#a7b7c1}.control-footer i.on{background:#26c79a}.arm-button{margin-left:auto;height:31px;padding:0 14px;background:#edf3f6;color:#648096}.telemetry-card{min-height:210px}.telemetry-line{display:grid;grid-template-columns:auto 1fr auto 1fr;gap:5px 8px;align-items:center;margin-top:13px;color:#8da0ae;font-size:10px}.telemetry-line strong{color:#37627d;font-size:11px}.release-button{width:100%;height:30px;margin-top:14px;border:1px solid #f0c8be;background:#fff5f1;color:#bd5b45}.release-button:disabled{color:#aab8c0;background:#f7fafb;border-color:#e4edf2}.release-note{display:block;margin-top:8px;color:#9aaab5;font-size:9px;line-height:1.5}.boat-error{margin:0;padding:8px 12px;border:1px solid #f0d2cc;border-radius:8px;background:#fff6f3;color:#bd5b45;font-size:11px}@media(max-width:1200px){.boat-hero{grid-template-columns:1fr}.boat-visual{min-height:230px}.boat-grid,.boat-control-grid{grid-template-columns:1fr 1fr}.boat-card:last-child{grid-column:1/span 2}}
/* 船载视角：Janus WebRTC 主画面 */
.boat-stream-card{min-height:0}.boat-stream-card header{margin-bottom:10px}.boat-stream-card header>div{display:flex;flex-direction:column;gap:3px}.boat-stream-card header small{color:#9aabba;font-size:9px}.fresh-text.stream-live{color:#1b9e76}.fresh-text.stream-connecting{color:#2b8fca}.fresh-text.stream-error{color:#c16b52}.boat-stream-viewport{position:relative;min-height:238px;overflow:hidden;border-radius:10px;background:#071a2e;box-shadow:inset 0 0 0 1px rgba(116,190,230,.18)}.boat-stream-video{display:block;width:100%;height:238px;object-fit:cover;background:#071a2e}.boat-stream-empty{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:#bfd1de;text-align:center;background:radial-gradient(circle at center,rgba(21,116,156,.24),rgba(4,21,39,.94) 64%)}.boat-stream-empty strong{font-size:13px;font-weight:600}.boat-stream-empty small{color:#7d9bae;font-size:9px}.stream-radar{position:relative;width:56px;height:56px;border:1px solid rgba(97,205,222,.45);border-radius:50%;background:repeating-radial-gradient(circle,transparent 0 12px,rgba(84,192,215,.18) 13px 14px)}.stream-radar:before{content:'';position:absolute;left:50%;top:5px;bottom:5px;width:1px;background:rgba(118,225,232,.42)}.stream-radar:after{content:'';position:absolute;top:50%;left:5px;right:5px;height:1px;background:rgba(118,225,232,.42)}.stream-radar span{position:absolute;left:50%;top:50%;width:6px;height:6px;border-radius:50%;background:#48d7cf;transform:translate(-50%,-50%);box-shadow:0 0 0 7px rgba(72,215,207,.12)}.stream-radar i{position:absolute;width:4px;height:4px;border-radius:50%;background:#42cbe0}.stream-radar i:first-child{left:14px;top:16px}.stream-radar i:nth-child(2){right:12px;bottom:14px}.stream-connect-button{height:31px;padding:0 14px;border:1px solid rgba(95,203,224,.45);border-radius:7px;background:rgba(23,138,174,.35);color:#d8fbff;font-size:10px;cursor:pointer}.stream-connect-button:disabled{cursor:not-allowed;opacity:.55}.stream-overlay,.stream-bottom{position:absolute;left:0;right:0;display:flex;align-items:center;justify-content:space-between;padding:9px 11px;color:#d6eef4;font-size:9px;background:linear-gradient(180deg,rgba(2,17,32,.7),transparent)}.stream-overlay{top:0}.stream-overlay>span:first-child{display:flex;align-items:center;gap:5px}.stream-overlay i{width:6px;height:6px;border-radius:50%;background:#95a8b4}.stream-overlay i.online{background:#37d3a2;box-shadow:0 0 0 3px rgba(55,211,162,.14)}.stream-overlay>span:last-child{color:#9ab4c4}.stream-bottom{bottom:0;background:linear-gradient(0deg,rgba(2,17,32,.78),transparent);color:#a8c5d0}.stream-bottom>div{display:flex;gap:7px}.stream-bottom button{border:1px solid rgba(188,229,238,.3);border-radius:5px;background:rgba(4,25,42,.48);color:#d4edf2;font-size:9px;padding:4px 7px;cursor:pointer}
</style>
