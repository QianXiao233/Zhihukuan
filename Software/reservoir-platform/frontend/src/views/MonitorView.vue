<template>
  <ViewShell title="运营总览" :tag="realtime ? 'MQTT 实时接入 · RTU 状态已收到' : mqttConnected ? 'MQTT 已连接 · 等待 RTU 状态' : '等待 MQTT 接入'" :icon="DashboardOutlined">
    <div class="overview-page">
      <section class="overview-metrics">
        <article v-for="metric in METRICS" :key="metric.label" class="overview-metric">
          <div class="overview-metric__icon" :class="metric.tone"><component :is="metric.icon" /></div>
          <div class="overview-metric__copy">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}<small>{{ metric.unit }}</small></strong>
            <em>{{ metric.hint }}</em>
          </div>
          <div class="overview-sparkline" :class="metric.tone"><i></i><i></i><i></i><i></i><i></i></div>
        </article>
      </section>

      <section class="overview-main-grid">
        <article class="overview-card twin-card">
          <header class="overview-card__head">
            <div><span class="section-icon section-icon--blue"><RadarChartOutlined /></span><h2>数字孪生沙盘</h2><span class="live-chip"><i></i>{{ twinStatus.failed ? '结构示意' : '三维沙盘' }}</span></div>
            <button type="button" class="text-action" @click="toggleMapFullscreen">{{ mapFullscreen ? '退出全屏' : '查看全屏' }} <RightOutlined /></button>
          </header>
            <div class="twin-map" :class="{ 'is-fullscreen': mapFullscreen }">
            <svg class="twin-map__terrain" viewBox="0 0 900 430" preserveAspectRatio="none" :aria-label="`${currentDamName}数字孪生地图`">
              <defs>
                <linearGradient id="terrainBg" x1="0" y1="0" x2="1" y2="1">
                  <stop offset="0" stop-color="#dff3f3" />
                  <stop offset="1" stop-color="#c7e8ea" />
                </linearGradient>
                <linearGradient id="lakeFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stop-color="#38bfe0" stop-opacity=".95" />
                  <stop offset="1" stop-color="#0d7fbb" stop-opacity=".92" />
                </linearGradient>
                <filter id="mapShadow"><feDropShadow dx="0" dy="5" stdDeviation="7" flood-color="#247d91" flood-opacity=".2"/></filter>
              </defs>
              <rect width="900" height="430" fill="url(#terrainBg)" />
              <path d="M0 58 C110 25 177 62 258 20 S420 8 502 60 S675 85 900 24 V0 H0Z" fill="#b5ddd9" opacity=".8"/>
              <path d="M0 363 C112 319 164 364 269 336 S445 310 532 354 S735 390 900 327 V430 H0Z" fill="#a4d0ca" opacity=".9"/>
              <path d="M80 160 C177 88 264 107 315 151 C356 187 383 152 424 124 C488 79 585 83 640 153 C698 226 772 180 820 153 L900 142 V290 C796 325 737 273 651 286 C564 299 524 350 430 300 C347 255 303 305 231 282 C177 264 125 292 60 258Z" fill="url(#lakeFill)" filter="url(#mapShadow)" />
              <path d="M102 160 C190 97 263 118 313 161 M643 164 C693 225 755 186 809 163 M64 253 C135 282 186 258 231 278" fill="none" stroke="#79d7da" stroke-width="3" stroke-dasharray="8 10" opacity=".85"/>
              <path d="M0 105 C140 61 200 121 302 78 S522 52 626 102 S782 124 900 73 M0 300 C127 259 222 320 324 279 S503 254 614 302 S794 331 900 287" fill="none" stroke="#75b8b7" stroke-width="2" opacity=".48"/>
              <path d="M340 324 L566 324 L593 351 L314 351Z" fill="#617d8f" opacity=".8"/>
              <path d="M332 322 L571 322" stroke="#f7fbfc" stroke-width="5"/>
              <g fill="#eaf8fa" stroke="#2a809c" stroke-width="2">
                <path d="M353 321 L353 291 L366 291 L366 321Z"/><path d="M396 321 L396 288 L409 288 L409 321Z"/>
                <path d="M440 321 L440 293 L453 293 L453 321Z"/><path d="M484 321 L484 287 L497 287 L497 321Z"/>
                <path d="M528 321 L528 294 L541 294 L541 321Z"/>
              </g>
              <path d="M408 238 C443 222 487 234 511 254 C541 281 567 287 596 270" fill="none" stroke="#d6ffff" stroke-width="3" stroke-dasharray="7 8"/>
              <circle cx="408" cy="238" r="6" fill="#fff" stroke="#138ec8" stroke-width="5"/>
              <circle cx="596" cy="270" r="6" fill="#fff" stroke="#19b998" stroke-width="5"/>
            </svg>
            <DamTwinScene
              ref="twinRef"
              :level="twinSceneLevel"
              :thresholds="twinSceneThresholds"
              :gates="twinGates"
              :alarm="twinAlarm"
              @status="onTwinStatus"
            />
            <TwinWeather />
            <TwinLabels :project="projectTwinPoint" />
            <button v-if="mapFullscreen" type="button" class="twin-fullscreen-exit" @click="toggleMapFullscreen">退出全屏</button>
            <div class="map-compass"><span>N</span><b>↗</b></div>
              <div class="map-mini">{{ currentDamName }}<br><small>{{ twinStatus.failed ? '结构示意 · 非实测地图' : '三维沙盘 · 拖拽旋转' }}</small></div>
          </div>
        </article>

        <article class="overview-card level-card">
          <header class="overview-card__head">
            <div><span class="section-icon section-icon--cyan"><DashboardOutlined /></span><h2>当前水位</h2></div><button type="button" class="fresh-text fresh-button" @click="goToMonitor">查看实时详情</button>
          </header>
          <div class="level-overview">
            <div class="level-gauge"><div><strong>{{ levelText }}</strong><small>m</small><span>当前水位</span></div></div>
            <div class="level-scale">
              <div><span>汛限水位</span><b>{{ displayValue(currentDam?.floodWaterLevel) }} m</b></div>
              <div><span>设计水位</span><b>{{ displayValue(currentDam?.designWaterLevel) }} m</b></div>
              <div><span>死水位</span><b>{{ displayValue(currentDam?.dieWaterLevel) }} m</b></div>
            </div>
          </div>
          <div class="level-status"><span><i :class="{ offline: !mqttConnected }"></i>MQTT</span><strong>{{ mqttConnected ? '已连接' : '等待接入' }}</strong><small>{{ levelHint }}</small></div>
        </article>

        <article class="overview-card gate-card">
          <header class="overview-card__head">
            <div><span class="section-icon section-icon--purple"><ControlOutlined /></span><h2>闸门状态</h2></div><button type="button" class="text-action" @click="goToBoat">进入控制台 <RightOutlined /></button>
          </header>
          <div class="gate-grid">
            <div v-for="gate in GATES" :key="gate.id" class="gate-item" :class="'gate-item--' + gate.tone">
              <span class="gate-item__symbol"><ControlOutlined /></span>
              <div><strong>{{ gate.id }}号闸门</strong><span><i></i>{{ gate.status }}</span></div>
              <button type="button" class="overview-gate-toggle" :class="gate.state ? 'is-open' : 'is-closed'" :disabled="!mqttConnected || !hasGateStatus" :aria-label="gate.state ? `关闭${gate.id}号闸门` : `开启${gate.id}号闸门`" @click="toggleGate(gate.id)"><span class="overview-gate-toggle__track"><i></i></span><span>{{ gate.state === null ? '—' : gate.state ? '开' : '关' }}</span></button>
            </div>
          </div>
          <p class="gate-note"><InfoCircleOutlined /> {{ !mqttConnected ? 'MQTT 未连接，暂不可控制闸门' : hasGateStatus ? '状态来自 rtu/status，控制发布到 rtu/control' : '已连接 MQTT，等待 rtu/status 闸门数据' }}</p>
        </article>
      </section>

      <section class="overview-bottom-grid">
        <article class="overview-card quality-card">
          <header class="overview-card__head"><div><span class="section-icon section-icon--green"><ExperimentOutlined /></span><h2>水质监测</h2></div><button type="button" class="text-action" @click="goToEcology">查看详情 <RightOutlined /></button></header>
          <div class="quality-list">
            <div v-for="item in QUALITY" :key="item.label" class="quality-item"><div class="quality-reading" :class="item.tone">{{ item.value }}<small>{{ item.unit }}</small></div><b>{{ item.label }}</b><small>{{ item.threshold }}</small></div>
          </div>
        </article>

        <article class="overview-card rain-card">
          <header class="overview-card__head"><div><span class="section-icon section-icon--blue"><LineChartOutlined /></span><h2>平台近期水位记录</h2></div><span class="fresh-text">全平台 · RTU 落库</span></header>
          <div v-if="historyChart.length" class="rain-chart"><div v-for="item in historyChart" :key="item.key" class="rain-column"><span>{{ item.value }}</span><i :style="{ height: `${item.height}px` }"></i><small>{{ item.label }}</small></div></div>
          <div v-else class="overview-empty">{{ historyLoading ? '正在读取历史记录…' : historyError || '数据库暂无水位记录' }}</div>
        </article>

        <article class="overview-card archive-card">
          <header class="overview-card__head"><div><span class="section-icon section-icon--orange"><BankOutlined /></span><h2>当前水库档案</h2></div><button type="button" class="text-action" @click="goToArchive">查看档案 <RightOutlined /></button></header>
          <strong class="archive-name">{{ currentDamName }}</strong>
          <div v-if="damError" class="archive-error">{{ damError }}</div>
          <div class="archive-meta"><span>{{ currentDam?.damType || '类型未填写' }}</span><span>{{ currentDam?.riverName || '所属河流未填写' }}</span></div>
          <div class="archive-location">{{ currentDam?.location || '所在位置未填写' }}</div>
          <div class="archive-stats">
            <div><small>坝高</small><b>{{ displayValue(currentDam?.damHeight) }} <i>m</i></b></div>
            <div><small>总库容</small><b>{{ displayValue(currentDam?.damStorage) }} <i>万 m³</i></b></div>
            <div><small>控制面积</small><b>{{ displayValue(currentDam?.controlArea) }} <i>km²</i></b></div>
          </div>
          <div class="archive-foot"><span>建成年份：{{ currentDam?.buildYear || '—' }}</span><span :class="currentDam?.status === 1 ? 'is-active' : 'is-disabled'">{{ currentDam ? (currentDam.status === 1 ? '启用' : '停用') : '暂无档案' }}</span></div>
        </article>
      </section>
    </div>
  </ViewShell>
</template>

<script setup>
import {
  BankOutlined,
  CloudOutlined,
  ControlOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  InfoCircleOutlined,
  LineChartOutlined,
  RadarChartOutlined,
  RightOutlined,
} from '@ant-design/icons-vue'
import { computed, nextTick, onMounted, ref } from 'vue'
import ViewShell from './ViewShell.vue'
import DamTwinScene from '../components/DamTwinScene.vue'
import TwinLabels from '../components/TwinLabels.vue'
import TwinWeather from '../components/TwinWeather.vue'
import { useRouter } from 'vue-router'
import { useReservoirMqtt } from '../composables/useReservoirMqtt.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'
import { dataSummary, listParams } from '../api/manageApi.js'

const router = useRouter()
const mapFullscreen = ref(false)
const twinRef = ref(null)
const twinStatus = ref({ failed: false, modelLoaded: false })
const { mqttConnected, realtime, gates, toggleGate } = useReservoirMqtt()
const { currentDam, currentDamName, loadDams } = useCurrentDam()
const params = ref([])
const historyRecords = ref([])
const historyLoading = ref(true)
const historyError = ref('')
const damError = ref('')
const hasRealtime = computed(() => Boolean(realtime.value))
const hasGateStatus = computed(() => Boolean(realtime.value?.relayReported))
const levelText = computed(() => realtime.value?.level == null ? '—' : Number(realtime.value.level).toFixed(2))
const levelHint = computed(() => !hasRealtime.value ? '等待 RTU 水位数据' : currentDam.value?.floodWaterLevel == null ? '档案未配置汛限水位' : `档案汛限 ${displayValue(currentDam.value.floodWaterLevel)} m`)

function toNumber(value) {
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? null : Number(value)
}

const twinLevel = computed(() => toNumber(realtime.value?.level))
const twinThresholds = computed(() => ({
  die: toNumber(currentDam.value?.dieWaterLevel),
  design: toNumber(currentDam.value?.designWaterLevel),
  flood: toNumber(currentDam.value?.floodWaterLevel),
}))
const twinGates = computed(() => (Array.isArray(gates.value) ? gates.value : []).map((state) => state === 1 ? 1 : 0))
const twinAlarm = computed(() => {
  const level = twinLevel.value
  const { design, flood } = twinThresholds.value
  if (level === null) return 0
  if (flood !== null && level >= flood) return 1
  if (design !== null && level >= design) return 0.45
  return 0
})

function onTwinStatus(status) {
  twinStatus.value = status
}

function projectTwinPoint(point) {
  return twinRef.value?.project(point)
}

/**
 * 三维沙盘的水位是“视觉水位”：RTU 的 level 是 0.2~5 m 的过程量，
 * 大坝档案的 28.3/38.36 m 是库容高程，两者不是同一基准。
 * 这里按监测参数的上下限把 level 归一化到模型自己的水位区间，避免水面掉进坑里。
 */
const waterParam = computed(() => findParam('water_level', 'level'))
const twinSceneThresholds = { die: 0.6, design: 1.4, flood: 1.55 }
const twinSceneLevel = computed(() => {
  const level = twinLevel.value
  const low = toNumber(waterParam.value?.paramLowValue)
  const high = toNumber(waterParam.value?.paramHighValue)
  if (level === null || low === null || high === null || high <= low) return 1.4
  const ratio = Math.min(1, Math.max(0, (level - low) / (high - low)))
  return 0.8 + ratio * 0.75
})

function displayValue(value) {
  return value === null || value === undefined || value === '' ? '—' : Number.isFinite(Number(value)) ? Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : value
}

function findParam(...codes) {
  const normalized = codes.map((code) => code.toLowerCase())
  return params.value.find((item) => normalized.includes(String(item.paramCode || '').toLowerCase()))
}

function thresholdLabel(codes, unit) {
  const item = findParam(...codes)
  if (!item || (item.paramLowValue == null && item.paramHighValue == null)) return '阈值未配置'
  const low = item.paramLowValue ?? '—'
  const high = item.paramHighValue ?? '—'
  return `${low} ~ ${high}${unit ? ` ${unit}` : ''}`
}

const METRICS = computed(() => [
  { label: '当前水位', value: realtime.value?.level != null ? realtime.value.level.toFixed(2) : '—', unit: 'm', hint: 'MQTT · level', tone: 'blue', icon: DashboardOutlined },
  { label: '液温', value: realtime.value?.temp != null ? realtime.value.temp.toFixed(1) : '—', unit: '℃', hint: 'MQTT · temp', tone: 'cyan', icon: CloudOutlined },
  { label: 'pH', value: realtime.value?.ph != null ? realtime.value.ph.toFixed(2) : '—', unit: '', hint: 'MQTT · ph', tone: 'green', icon: ExperimentOutlined },
  { label: 'ORP', value: realtime.value?.orp != null ? realtime.value.orp.toFixed(0) : '—', unit: 'mV', hint: 'MQTT · orp', tone: 'purple', icon: RadarChartOutlined },
])

const GATES = computed(() => gates.value.map((state, index) => ({ id: index + 1, state: hasGateStatus.value ? state === 1 : null, status: !hasGateStatus.value ? '等待数据' : state === 1 ? '开启' : '关闭', tone: !hasGateStatus.value ? 'off' : state === 1 ? 'on' : 'off' })))

const QUALITY = computed(() => [
  { label: 'pH', value: realtime.value?.ph == null ? '—' : Number(realtime.value.ph).toFixed(2), unit: '', threshold: thresholdLabel(['ph'], ''), tone: 'blue' },
  { label: '液温', value: realtime.value?.temp == null ? '—' : Number(realtime.value.temp).toFixed(1), unit: '℃', threshold: thresholdLabel(['temperature', 'temp'], '℃'), tone: 'cyan' },
  { label: 'ORP', value: realtime.value?.orp == null ? '—' : Number(realtime.value.orp).toFixed(0), unit: 'mV', threshold: thresholdLabel(['orp'], 'mV'), tone: 'orange' },
])

const historyChart = computed(() => {
  const rows = [...historyRecords.value].reverse().filter((row) => row.level !== null && row.level !== undefined && Number.isFinite(Number(row.level)))
  if (!rows.length) return []
  const values = rows.map((row) => Number(row.level))
  const low = Math.min(...values), high = Math.max(...values), range = high - low
  return rows.map((row, index) => {
    const time = row.time ? new Date(row.time) : null
    return { key: row.id ?? `${row.time}-${index}`, value: Number(row.level).toFixed(2), height: range ? Math.round(18 + ((Number(row.level) - low) / range) * 76) : 48, label: time && !Number.isNaN(time.getTime()) ? time.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) : '—' }
  })
})

async function loadOverviewData() {
  const [damResult, paramResult, historyResult] = await Promise.allSettled([loadDams(), listParams(), dataSummary(7, 1)])
  if (damResult.status === 'rejected') damError.value = damResult.reason?.message || '水库档案读取失败'
  if (paramResult.status === 'fulfilled') params.value = paramResult.value.data || []
  if (historyResult.status === 'fulfilled') historyRecords.value = historyResult.value.data?.recent || []
  else historyError.value = historyResult.reason?.message || '历史记录读取失败'
  historyLoading.value = false
}

function goToBoat() { void router.push({ name: 'flood' }) }
function goToMonitor() { void router.push({ name: 'monitor-detail' }) }
function goToEcology() { void router.push({ name: 'ecology' }) }
function goToArchive() { void router.push({ name: 'dam' }) }
async function toggleMapFullscreen() {
  mapFullscreen.value = !mapFullscreen.value
  await nextTick()
  twinRef.value?.resize()
}

onMounted(() => { void loadOverviewData() })
</script>

<style scoped>
.overview-page { display: flex; flex-direction: column; gap: 15px; min-width: 920px; }
.overview-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; }
.overview-metric, .overview-card { border: 1px solid #e2ebf3; border-radius: 15px; background: rgba(255,255,255,.92); box-shadow: 0 8px 22px rgba(31, 80, 117, .07); }
.overview-metric { min-height: 122px; display: flex; align-items: center; gap: 12px; padding: 17px 17px; overflow: hidden; }
.overview-metric__icon { display: flex; align-items: center; justify-content: center; flex: 0 0 42px; width: 42px; height: 42px; border-radius: 14px; color: #fff; font-size: 20px; }
.overview-metric__icon.blue { background: linear-gradient(145deg,#60b8ff,#2884ea); }
.overview-metric__icon.cyan { background: linear-gradient(145deg,#63dbef,#23b6db); }
.overview-metric__icon.green { background: linear-gradient(145deg,#63ddb2,#28bd8e); }
.overview-metric__icon.purple { background: linear-gradient(145deg,#a89cf9,#7569df); }
.overview-metric__copy { min-width: 0; flex: 1; }
.overview-metric__copy > span { display: block; color: #748aa1; font-size: 11px; }
.overview-metric__copy > strong { display: block; margin: 4px 0 3px; color: #163956; font-size: 24px; line-height: 1.15; font-weight: 700; }
.overview-metric__copy > strong small { margin-left: 4px; color: #748aa1; font-size: 11px; font-weight: 500; }
.overview-metric__copy > em { display: block; color:#8195a8; font-size: 10px; font-style: normal; white-space: nowrap; }

.overview-main-grid { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(300px, .88fr); grid-template-rows: 310px 210px; gap: 15px; }
.overview-card { min-width: 0; padding: 15px 16px; overflow: hidden; }
.twin-card { grid-row: 1 / span 2; }
.overview-card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 12px; }
.overview-card__head > div { display: flex; align-items: center; gap: 8px; min-width: 0; }
.overview-card__head h2 { margin: 0; color: #1b3e5c; font-size: 14px; font-weight: 650; white-space: nowrap; }
.section-icon { display: inline-flex; align-items: center; justify-content: center; width: 25px; height: 25px; border-radius: 8px; font-size: 13px; }
.section-icon--blue { background: #e9f4ff; color: #2985df; }.section-icon--cyan { background: #e7faff; color: #1baccd; }.section-icon--purple { background: #f1eeff; color: #796bda; }.section-icon--green { background: #e8fbf2; color: #21a879; }.section-icon--orange { background: #fff4e9; color: #e99435; }
.live-chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 7px; border-radius: 10px; background: #e7fbf3; color: #1b9e76; font-size: 9px; }
.live-chip i { width: 5px; height: 5px; border-radius: 50%; background: #28c995; }
.text-action { display: inline-flex; align-items: center; gap: 3px; border: 0; background: transparent; color: #77a0c4; font-size: 10px; cursor: pointer; white-space: nowrap; }
.text-action:hover { color: #1676e8; }
.fresh-text { color: #9aabbc; font-size: 10px; white-space: nowrap; }

.twin-map { position: relative; height: calc(100% - 39px); min-height: 390px; overflow: hidden; border-radius: 11px; background: #0a2029; }
.twin-map__terrain { position: absolute; inset: 0; z-index: 0; width: 100%; height: 100%; }
.map-compass { position: absolute; right: 13px; bottom: 13px; z-index: 2; display: flex; flex-direction: column; align-items: center; color: #9fd8ee; font-size: 9px; pointer-events: none; }.map-compass b { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; margin-top: 2px; border-radius: 50%; background: rgba(6, 30, 42, .72); color: #7fe0ff; font-size: 18px; border: 1px solid rgba(79, 209, 255, .35); }
.map-mini { position: absolute; left: 13px; bottom: 13px; z-index: 2; padding: 7px 10px; border-radius: 6px; background: rgba(6, 30, 42, .72); color: #e9fdff; font-size: 10px; border: 1px solid rgba(79, 209, 255, .25); pointer-events: none; }.map-mini small { color: #9fd8ee; font-size: 8px; }
.twin-fullscreen-exit { position: absolute; top: 12px; right: 12px; z-index: 3; padding: 6px 12px; border: 1px solid rgba(79, 209, 255, .45); border-radius: 7px; background: rgba(6, 30, 42, .82); color: #dff8ff; font-size: 11px; cursor: pointer; }
.twin-fullscreen-exit:hover { border-color: #7fe0ff; background: rgba(10, 52, 70, .9); }

.level-card { display: flex; flex-direction: column; }
.level-overview { display: flex; align-items: center; gap: 17px; min-height: 140px; }
.level-gauge { display: flex; align-items: center; justify-content: center; flex: 0 0 128px; width: 128px; height: 128px; border-radius: 50%; background: #e7f0f5; position: relative; }
.level-gauge::before { content: ''; position: absolute; inset: 10px; border-radius: 50%; background: #fff; }.level-gauge > div { position: relative; z-index: 1; text-align: center; }.level-gauge strong { color: #1c4d72; font-size: 22px; line-height: 1; }.level-gauge small { margin-left: 2px; color: #5f7891; font-size: 10px; }.level-gauge span { display: block; margin-top: 4px; color: #8095a8; font-size: 9px; }
.level-scale { flex: 1; display: flex; flex-direction: column; gap: 15px; }.level-scale > div { display: flex; justify-content: space-between; gap: 8px; color: #7b91a5; font-size: 10px; }.level-scale b { color: #486781; font-size: 10px; font-weight: 600; white-space: nowrap; }
.level-status { display: flex; align-items: center; gap: 10px; margin-top: auto; padding: 9px 10px; border-radius: 8px; background: #f3faf8; font-size: 10px; }.level-status span { display: inline-flex; align-items: center; gap: 5px; color: #6b8b9a; }.level-status i { width: 6px; height: 6px; border-radius: 50%; background: #25c395; }.level-status strong { color: #19966f; font-size: 10px; }.level-status small { margin-left: auto; color: #8297a6; }

.gate-card { display: flex; flex-direction: column; }.gate-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }.gate-item { display: flex; align-items: center; gap: 7px; padding: 10px 7px; border: 1px solid #e5edf4; border-radius: 9px; background: #fbfdfe; }.gate-item__symbol { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 7px; background: #e6f8f7; color: #20af9a; font-size: 14px; }.gate-item--off .gate-item__symbol { background: #eef3f7; color: #7691a4; }.gate-item--warn .gate-item__symbol { background: #fff3e6; color: #eb9d38; }.gate-item strong { display: block; color: #385772; font-size: 10px; font-weight: 600; }.gate-item span:not(.gate-item__symbol) { display: inline-flex; align-items: center; gap: 4px; margin-top: 3px; color: #22a37f; font-size: 9px; }.gate-item--off span:not(.gate-item__symbol) { color: #8399aa; }.gate-item--warn span:not(.gate-item__symbol) { color: #d78b28; }.gate-item span i { width: 5px; height: 5px; border-radius: 50%; background: currentColor; }.gate-note { display: flex; align-items: center; gap: 5px; margin: auto 0 0; color: #9aaab8; font-size: 9px; }.gate-note :deep(svg) { color: #93aec2; }

.overview-bottom-grid { display: grid; grid-template-columns: 1fr 1fr 1.15fr; gap: 15px; }.quality-card, .rain-card, .archive-card { min-height: 182px; }.quality-list { display: grid; grid-template-columns: repeat(3, 1fr); align-items: start; gap: 7px; margin-top: 24px; }.quality-item { min-width: 0; text-align: center; }.quality-reading { color: #315a77; font-size: 17px; font-weight: 650; white-space: nowrap; }.quality-reading small { margin-left: 2px; color: #748da1; font-size: 9px; font-weight: 500; }.quality-reading.cyan { color: #179daf; }.quality-reading.orange { color: #c6812d; }.quality-item b { display: block; margin-top: 4px; color: #517088; font-size: 10px; }.quality-item > small { display: block; margin-top: 5px; color: #99aab9; font-size: 8px; white-space: nowrap; }

.rain-chart { display: flex; align-items: flex-end; justify-content: space-around; height: 116px; padding: 8px 5px 0; border-bottom: 1px solid #eaf0f5; background: repeating-linear-gradient(to bottom, transparent 0 31px, #edf3f7 32px); }.rain-column { position: relative; min-width: 0; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; gap: 5px; }.rain-column span { color: #5d83a3; font-size: 8px; }.rain-column i { display: block; width: 13px; max-height: 94px; min-height: 8px; border-radius: 5px 5px 2px 2px; background: linear-gradient(180deg, #39b9f0, #287edc); }.rain-column small { color: #8ca0b2; font-size: 8px; white-space: nowrap; }.overview-empty { display:flex; align-items:center; justify-content:center; height:112px; color:#91a4b2; font-size:10px; text-align:center; }.archive-name { display:block; margin-top:2px; color:#234d6d; font-size:15px; }.archive-error { margin-top:5px; color:#bd5b52; font-size:9px; }.archive-meta { display:flex; flex-wrap:wrap; gap:6px; margin-top:6px; color:#66849a; font-size:9px; }.archive-meta span { padding:3px 7px; border-radius:8px; background:#f0f6fa; }.archive-location { overflow:hidden; margin-top:7px; color:#879cab; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }.archive-stats { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:12px; padding:10px 0; border-top:1px solid #edf2f5; border-bottom:1px solid #edf2f5; }.archive-stats small,.archive-stats b { display:block; }.archive-stats small { color:#94a6b3; font-size:8px; }.archive-stats b { overflow:hidden; margin-top:4px; color:#315d7d; font-size:11px; text-overflow:ellipsis; white-space:nowrap; }.archive-stats i { color:#8a9ead; font-size:8px; font-style:normal; font-weight:400; }.archive-foot { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-top:9px; color:#91a1ad; font-size:9px; }.archive-foot span:last-child { padding:3px 7px; border-radius:7px; }.archive-foot .is-active { background:#e8faf3; color:#168b69; }.archive-foot .is-disabled { background:#f1f4f6; color:#8498a6; }


@media (max-width: 1200px) { .overview-main-grid { grid-template-columns: minmax(0, 1.35fr) minmax(280px, .9fr); }.overview-bottom-grid { grid-template-columns: 1fr 1fr; }.archive-card { grid-column: 1 / span 2; }.gate-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

.twin-map.is-fullscreen{position:fixed;z-index:30;inset:70px 32px 28px 284px;height:auto;min-height:0;border:5px solid #fff;box-shadow:0 18px 50px rgba(5,30,53,.35)}.fresh-button{border:0;background:transparent;cursor:pointer}.overview-gate-toggle{display:inline-flex;align-items:center;gap:4px;margin-left:auto;padding:3px 5px 3px 4px;border:1px solid #dce8ef;border-radius:8px;background:#f5f9fb;color:#7d95a5;font-size:9px;cursor:pointer;transition:.18s ease}.overview-gate-toggle:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 4px 8px rgba(38,102,142,.12)}.overview-gate-toggle:disabled{cursor:not-allowed;opacity:.45}.overview-gate-toggle__track{position:relative;width:27px;height:15px;border-radius:99px;background:#d7e3eb}.overview-gate-toggle__track i{position:absolute;top:2px;left:2px;width:11px;height:11px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(20,64,88,.22);transition:.18s ease}.overview-gate-toggle.is-open{border-color:#b7ead8;background:#effbf6;color:#168c6c}.overview-gate-toggle.is-open .overview-gate-toggle__track{background:#2abf92}.overview-gate-toggle.is-open .overview-gate-toggle__track i{transform:translateX(12px)}

@media (max-width: 900px) {
  .overview-page { min-width: 0; gap: 10px; }
  .overview-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .overview-metric { min-height: 96px; padding: 12px; gap: 9px; }
  .overview-metric__icon { flex-basis: 34px; width: 34px; height: 34px; font-size: 16px; }
  .overview-metric__copy > strong { font-size: 20px; }
  .overview-main-grid { grid-template-columns: 1fr; grid-template-rows: none; gap: 10px; }
  .twin-card { grid-row: auto; }
  .twin-map { height: 280px; min-height: 0; }
  .twin-map.is-fullscreen { inset: 56px 8px 8px; border-width: 3px; }
  .level-card, .gate-card { min-height: 0; }
  .level-overview { min-height: 110px; gap: 12px; }
  .level-gauge { flex-basis: 100px; width: 100px; height: 100px; }
  .level-gauge strong { font-size: 18px; }
  .gate-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .overview-bottom-grid { grid-template-columns: 1fr; gap: 10px; }
  .archive-card { grid-column: auto; }
  .quality-list { margin-top: 10px; }
  .rain-chart { height: 100px; }
  .rain-column i { max-height: 78px; }
}
</style>



