<template>
  <ViewShell title="实时监测" :tag="realtime ? 'MQTT 实时数据已接收' : mqttConnected ? 'MQTT 已连接 · 等待 RTU 状态' : '等待 MQTT 接入'" :icon="DashboardOutlined">
    <div class="monitor-page">
      <section class="monitor-metrics">
        <article v-for="item in metrics" :key="item.label" class="monitor-metric">
          <span class="monitor-metric__label">{{ item.label }}</span>
          <strong>{{ item.value }}<small>{{ item.unit }}</small></strong>
          <em>{{ item.hint }}</em>
        </article>
      </section>

      <section v-if="serverStatus" class="alert-strip" :class="{ 'has-alert': violations.length }">
        <span class="alert-strip__icon"><AlertOutlined /></span>
        <div class="alert-strip__copy">
          <strong>{{ violations.length ? `后端检出 ${violations.length} 项读数超出阈值` : '后端实时监控正常' }}</strong>
          <small>{{ alertStateText }}<template v-if="cooldownText"> · {{ cooldownText }}</template></small>
        </div>
        <div class="alert-strip__chips">
          <span v-for="item in violations" :key="item.code">{{ item.name }} {{ item.value }}{{ item.unit }} · {{ item.direction }}</span>
        </div>
      </section>
      <p v-if="statusError" class="table-note">告警状态读取失败：{{ statusError }}</p>

      <section class="monitor-grid">
        <article class="monitor-card monitor-card--wide">
          <header><div><DashboardOutlined /><h2>RTU 实时监测数据</h2></div><span>{{ lastUpdated }}</span></header>
          <table class="monitor-table">
            <thead><tr><th>监测参数</th><th>类型</th><th>当前读数</th><th>数据库阈值</th><th>判断</th></tr></thead>
            <tbody>
              <tr v-for="row in sensorRows" :key="row.code">
                <td>{{ row.name }}</td><td>{{ row.type }}</td><td>{{ row.value }}</td><td>{{ row.threshold }}</td>
                <td><b class="status" :class="row.state">{{ row.stateText }}</b></td>
              </tr>
            </tbody>
          </table>
          <p v-if="paramError" class="table-note">监测阈值读取失败：{{ paramError }}</p>
        </article>

        <article class="monitor-card">
          <header><div><LineChartOutlined /><h2>历史水位</h2></div><span>数据库 · 最近 {{ historyRows.length }} 条</span></header>
          <template v-if="trendPoints.length">
            <div class="line-chart"><i v-for="point in trendPoints" :key="point.key" :style="{ left: `${point.x}%`, top: `${point.y}%` }"></i><svg viewBox="0 0 100 100" preserveAspectRatio="none"><polyline :points="trendPolyline" fill="none" stroke="#2e9be8" stroke-width="2.5" vector-effect="non-scaling-stroke" /></svg></div>
            <div class="chart-scale"><span v-for="point in trendScale" :key="point.key">{{ point.label }}</span></div>
          </template>
          <div v-else class="chart-empty">{{ historyLoading ? '正在读取数据库记录…' : historyError || '数据库暂无水情记录' }}</div>
        </article>
      </section>

      <section class="monitor-card monitor-card--alerts">
        <header><div><BellOutlined /><h2>最近告警与推送</h2></div><span>冷却 {{ serverStatus?.alert?.cooldownMinutes ?? '—' }} 分钟 · 抑制 {{ serverStatus?.alert?.suppressedCount ?? 0 }} 次</span></header>
        <div v-if="recentAlerts.length" class="alert-list">
          <div v-for="item in recentAlerts" :key="item.id || item.time" class="alert-item">
            <i :class="item.pushed ? 'sent' : 'pending'"></i>
            <div>
              <strong>{{ item.metricName }} {{ item.value ?? '—' }}{{ item.unit }} <small>{{ item.direction }}</small></strong>
              <small>{{ item.timeText }} · 阈值 {{ item.low ?? '—' }} ~ {{ item.high ?? '—' }}</small>
            </div>
            <b :class="item.pushed ? 'sent' : 'failed'">{{ statusText(item.status) }}</b>
          </div>
        </div>
        <div v-else class="device-empty">暂无告警记录</div>
      </section>

      <section class="monitor-card monitor-card--table">
        <header><div><ExperimentOutlined /><h2>当前水库设备台账</h2></div><span>{{ enabledDeviceCount }} 台启用 / 共 {{ selectedDevices.length }} 台</span></header>
        <div v-if="selectedDevices.length" class="device-list">
          <div v-for="device in selectedDevices" :key="device.deviceId" class="device-item">
            <i :class="device.status === 1 ? 'enabled' : 'disabled'"></i>
            <div><strong>{{ device.deviceName || '未命名设备' }}</strong><small>{{ device.deviceType || '类型未填写' }} · {{ device.deviceCode || '未填写编码' }}</small></div>
            <span>{{ device.installPosition || '位置未填写' }}</span>
            <b :class="device.status === 1 ? 'enabled' : 'disabled'">{{ device.status === 1 ? '启用' : '停用' }}</b>
          </div>
        </div>
        <div v-else class="device-empty">{{ deviceLoading ? '正在读取设备台账…' : deviceError || '当前水库暂无设备台账' }}</div>
      </section>
    </div>
  </ViewShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { AlertOutlined, BellOutlined, DashboardOutlined, ExperimentOutlined, LineChartOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { useReservoirMqtt } from '../composables/useReservoirMqtt.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'
import { dataSummary, listDevices, listParams, monitorStatus } from '../api/manageApi.js'

const { mqttConnected, realtime } = useReservoirMqtt()
const { selectedDamId, loadDams } = useCurrentDam()
const params = ref([])
const historyRows = ref([])
const devices = ref([])
const historyLoading = ref(true)
const deviceLoading = ref(true)
const historyError = ref('')
const deviceError = ref('')
const paramError = ref('')
const serverStatus = ref(null)
const statusError = ref('')
let statusTimer

const definitions = [
  { code: 'water_level', aliases: ['water_level', 'level'], label: '水位', type: '水情', field: 'level', unit: 'm', digits: 2 },
  { code: 'temperature', aliases: ['temperature', 'temp'], label: '液温', type: '水质', field: 'temp', unit: '℃', digits: 1 },
  { code: 'ph', aliases: ['ph'], label: 'pH', type: '水质', field: 'ph', unit: '', digits: 2 },
  { code: 'orp', aliases: ['orp'], label: 'ORP', type: '水质', field: 'orp', unit: 'mV', digits: 0 },
]

function parameterFor(definition) {
  return params.value.find((item) => definition.aliases.includes(String(item.paramCode || '').toLowerCase()))
}

function formatNumber(value, digits = 2) {
  return value === null || value === undefined || value === '' || !Number.isFinite(Number(value)) ? '—' : Number(value).toFixed(digits)
}

function formatThreshold(definition) {
  const parameter = parameterFor(definition)
  if (!parameter || (parameter.paramLowValue == null && parameter.paramHighValue == null)) return '未配置'
  return `${parameter.paramLowValue ?? '—'} ~ ${parameter.paramHighValue ?? '—'}${definition.unit ? ` ${definition.unit}` : ''}`
}

const metrics = computed(() => definitions.map((definition) => ({
  label: definition.label,
  value: formatNumber(realtime.value?.[definition.field], definition.digits),
  unit: definition.unit,
  hint: realtime.value ? `MQTT · ${definition.field}` : '等待 MQTT 数据',
})))

const lastUpdated = computed(() => realtime.value?.receivedAt
  ? `最近接收 ${new Date(realtime.value.receivedAt).toLocaleTimeString('zh-CN', { hour12: false })}`
  : mqttConnected.value ? '已连接，尚未收到 RTU 状态' : '等待 MQTT 接入')

const sensorRows = computed(() => definitions.map((definition) => {
  const raw = realtime.value?.[definition.field]
  const value = raw == null ? null : Number(raw)
  const parameter = parameterFor(definition)
  const low = Number(parameter?.paramLowValue)
  const high = Number(parameter?.paramHighValue)
  const hasLow = parameter?.paramLowValue !== null && parameter?.paramLowValue !== undefined && parameter.paramLowValue !== '' && Number.isFinite(low)
  const hasHigh = parameter?.paramHighValue !== null && parameter?.paramHighValue !== undefined && parameter.paramHighValue !== '' && Number.isFinite(high)
  const hasThreshold = hasLow || hasHigh
  const outside = value !== null && hasThreshold && ((hasLow && value < low) || (hasHigh && value > high))
  return {
    ...definition,
    name: parameter?.paramName || definition.label,
    value: value === null ? '等待数据' : `${formatNumber(value, definition.digits)}${definition.unit ? ` ${definition.unit}` : ''}`,
    threshold: formatThreshold(definition),
    state: value === null || !hasThreshold ? 'pending' : outside ? 'warning' : 'ok',
    stateText: value === null ? '等待数据' : !hasThreshold ? '未配置阈值' : outside ? '超出阈值' : '阈值内',
  }
}))

const trendPoints = computed(() => {
  const rows = [...historyRows.value].reverse().filter((row) => row.level !== null && row.level !== undefined && Number.isFinite(Number(row.level)))
  if (!rows.length) return []
  const values = rows.map((row) => Number(row.level))
  const min = Math.min(...values), max = Math.max(...values), spread = max - min
  return rows.map((row, index) => {
    const date = row.time ? new Date(row.time) : null
    return {
      key: row.id ?? `${row.time}-${index}`,
      x: rows.length === 1 ? 50 : 4 + (index / (rows.length - 1)) * 92,
      y: spread ? 90 - ((Number(row.level) - min) / spread) * 78 : 51,
      label: date && !Number.isNaN(date.getTime()) ? date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }) : '—',
    }
  })
})
const trendPolyline = computed(() => trendPoints.value.map((point) => `${point.x},${point.y}`).join(' '))
const trendScale = computed(() => {
  const points = trendPoints.value
  if (points.length <= 3) return points
  return [points[0], points[Math.floor((points.length - 1) / 2)], points[points.length - 1]]
})
const selectedDevices = computed(() => {
  if (!selectedDamId.value) return []
  return devices.value.filter((device) => String(device.damId) === String(selectedDamId.value))
})
const enabledDeviceCount = computed(() => selectedDevices.value.filter((device) => device.status === 1).length)

async function loadViewData() {
  const [damResult, paramResult, historyResult, deviceResult] = await Promise.allSettled([loadDams(), listParams(), dataSummary(12, 1), listDevices()])
  if (damResult.status === 'rejected') deviceError.value = damResult.reason?.message || '水库档案读取失败'
  if (paramResult.status === 'fulfilled') params.value = paramResult.value.data || []
  else paramError.value = paramResult.reason?.message || '阈值读取失败'
  if (historyResult.status === 'fulfilled') historyRows.value = historyResult.value.data?.recent || []
  else historyError.value = historyResult.reason?.message || '历史记录读取失败'
  if (deviceResult.status === 'fulfilled') devices.value = deviceResult.value.data || []
  else deviceError.value = deviceResult.reason?.message || '设备台账读取失败'
  historyLoading.value = false
  deviceLoading.value = false
}

const violations = computed(() => serverStatus.value?.violations || [])
const recentAlerts = computed(() => serverStatus.value?.recentAlerts || [])
const alertStateText = computed(() => {
  const alert = serverStatus.value?.alert
  if (!alert) return '正在读取推送状态'
  if (!alert.alertEnabled) return '实时阈值告警已停用'
  if (!alert.pushEnabled) return '推送开关已关闭'
  if (!alert.tokenConfigured) return '未配置推送 token，告警不会外发'
  return '推送通道就绪'
})
const cooldownText = computed(() => {
  const remaining = serverStatus.value?.alert?.cooldownRemaining || {}
  const items = Object.entries(remaining).filter(([, seconds]) => Number(seconds) > 0)
  if (!items.length) return ''
  return items.map(([key, seconds]) => `${key.replace('metric:', '')} 冷却 ${Math.ceil(Number(seconds) / 60)} 分钟`).join('，')
})
function statusText(status) {
  return ({ sent: '已推送', queued: '推送中', failed: '推送失败', skipped: '未推送', 'no-token': '缺 token' })[status] || status || '—'
}

async function loadStatus() {
  try {
    serverStatus.value = (await monitorStatus()).data || null
    statusError.value = ''
  } catch (e) {
    statusError.value = e.message
  }
}

onMounted(() => { void loadViewData(); void loadStatus(); statusTimer = window.setInterval(loadStatus, 20000) })
onBeforeUnmount(() => { if (statusTimer) window.clearInterval(statusTimer) })
</script>

<style scoped>
.monitor-page { display: flex; flex-direction: column; gap: 15px; min-width: 920px; }
.monitor-metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; }
.monitor-metric, .monitor-card { border: 1px solid #e2ebf3; border-radius: 15px; background: #fff; box-shadow: 0 8px 22px rgba(31,80,117,.06); }
.monitor-metric { padding: 18px; }.monitor-metric__label { display:block; color:#7188a0; font-size:11px; }.monitor-metric strong { display:block; margin:7px 0 3px; color:#163956; font-size:26px; }.monitor-metric strong small { margin-left:4px; color:#7188a0; font-size:11px; font-weight:500; }.monitor-metric em { color:#8196a6; font-size:10px; font-style:normal; }
.monitor-grid { display:grid; grid-template-columns:1.45fr 1fr; gap:15px; }.monitor-card { min-width:0; padding:16px; overflow:hidden; }.monitor-card header { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:14px; }.monitor-card header div { display:flex; align-items:center; gap:8px; color:#2385db; }.monitor-card h2 { margin:0; color:#1b3e5c; font-size:14px; }.monitor-card header>span { color:#98aabb; font-size:10px; text-align:right; }
.monitor-table { width:100%; border-collapse:collapse; color:#557188; font-size:11px; }.monitor-table th { padding:9px 8px; color:#88a0b2; font-weight:500; text-align:left; background:#f6f9fb; }.monitor-table td { padding:11px 8px; border-bottom:1px solid #edf2f5; }.monitor-table tr:last-child td { border-bottom:0; }.status { padding:3px 8px; border-radius:9px; font-size:10px; font-weight:500; white-space:nowrap; }.status.ok { color:#168b69; background:#e8faf3; }.status.warning { color:#b57322; background:#fff5e5; }.status.pending { color:#738b9c; background:#eff4f7; }.table-note { margin:8px 0 0; color:#b17d38; font-size:9px; }
.line-chart { position:relative; height:150px; border-bottom:1px solid #eaf0f5; background:repeating-linear-gradient(to bottom,transparent 0 36px,#edf3f7 37px); }.line-chart svg { position:absolute; inset:0; width:100%; height:100%; overflow:visible; }.line-chart>i { position:absolute; z-index:2; width:7px; height:7px; transform:translate(-50%,-50%); border:2px solid #fff; border-radius:50%; background:#2e9be8; box-shadow:0 0 0 1px #2e9be8; }.chart-scale { display:flex; justify-content:space-between; gap:3px; padding-top:8px; color:#93a5b4; font-size:8px; }.chart-scale span { min-width:0; overflow:hidden; text-overflow:ellipsis; }.chart-empty,.device-empty { display:flex; align-items:center; justify-content:center; min-height:150px; color:#91a4b2; font-size:11px; text-align:center; }
.monitor-card--table { min-height:160px; }.device-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:9px; }.device-item { display:grid; grid-template-columns:8px minmax(100px,1fr) minmax(65px,auto) auto; align-items:center; gap:8px; padding:10px 12px; border:1px solid #eaf0f4; border-radius:9px; background:#fbfdfe; }.device-item>i { width:7px; height:7px; border-radius:50%; }.device-item>i.enabled { background:#2ac49a; }.device-item>i.disabled { background:#d2a24d; }.device-item strong,.device-item small { display:block; }.device-item strong { color:#355571; font-size:11px; }.device-item small,.device-item>span { overflow:hidden; color:#92a4b3; font-size:9px; text-overflow:ellipsis; white-space:nowrap; }.device-item>b { padding:3px 7px; border-radius:9px; font-size:9px; font-weight:500; }.device-item>b.enabled { color:#168b69; background:#e8faf3; }.device-item>b.disabled { color:#a97827; background:#fff4e3; }
@media (max-width: 1200px) { .monitor-metrics { grid-template-columns:repeat(2,1fr); }.monitor-grid { grid-template-columns:1fr; }.device-list { grid-template-columns:1fr; } }
.alert-strip { display:flex; align-items:center; gap:12px; padding:12px 16px; border:1px solid #d7ecdf; border-radius:13px; background:#f5fcf9; }
.alert-strip.has-alert { border-color:#f2d9d6; background:#fff8f7; }
.alert-strip__icon { display:flex; align-items:center; justify-content:center; width:30px; height:30px; flex:0 0 30px; border-radius:9px; background:#e8faf3; color:#168b69; font-size:15px; }
.alert-strip.has-alert .alert-strip__icon { background:#ffeceb; color:#c25854; }
.alert-strip__copy { flex:1; min-width:0; }
.alert-strip__copy strong, .alert-strip__copy small { display:block; }
.alert-strip__copy strong { color:#294b66; font-size:13px; }
.alert-strip__copy small { margin-top:3px; color:#8a9daa; font-size:10px; }
.alert-strip__chips { display:flex; flex-wrap:wrap; gap:6px; }
.alert-strip__chips span { padding:4px 9px; border-radius:9px; background:#fff1ef; color:#b64c4a; font-size:10px; }
.monitor-card--alerts { min-height:120px; }
.alert-list { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.alert-item { display:grid; grid-template-columns:8px minmax(0,1fr) auto; align-items:center; gap:9px; padding:9px 11px; border:1px solid #eef2f5; border-radius:9px; background:#fbfdfe; }
.alert-item > i { width:7px; height:7px; border-radius:50%; background:#d2a24d; }
.alert-item > i.sent { background:#2ac49a; }
.alert-item strong, .alert-item small { display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.alert-item strong { color:#355571; font-size:11px; }
.alert-item strong small { display:inline; color:#b57322; font-size:9px; font-weight:500; }
.alert-item small { margin-top:2px; color:#93a5b4; font-size:9px; }
.alert-item > b { padding:3px 7px; border-radius:9px; background:#e8faf3; color:#168b69; font-size:9px; font-weight:500; }
.alert-item > b.failed { background:#fff1ef; color:#b64c4a; }
@media (max-width:900px) { .alert-list { grid-template-columns:1fr; }.alert-strip { flex-wrap:wrap; } }
</style>
