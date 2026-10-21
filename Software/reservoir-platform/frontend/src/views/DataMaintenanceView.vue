<template>
  <ViewShell title="数据维护" :tag="`MongoDB · ${count} 条记录`" :icon="DatabaseOutlined">
    <div class="data-page">
      <!-- 存储引擎状态 -->
      <section class="engine-bar" :class="storageOk ? 'is-online' : 'is-offline'">
        <span class="engine-dot"></span>
        <div class="engine-copy">
          <strong>{{ storage ? (storageOk ? 'MongoDB 已连接' : 'MongoDB 未连接') : '正在检测存储状态' }}</strong>
          <small v-if="storage">
            集合 {{ storage.collection }} · 文档 {{ storage.documents ?? '—' }} 条
            <template v-if="storage.legacyMysqlCount !== null && storage.legacyMysqlCount !== undefined"> · 旧 MySQL 表 {{ storage.legacyMysqlCount }} 条</template>
            <template v-if="storage.latestTime"> · 最新 {{ formatTime(storage.latestTime) }}</template>
          </small>
          <small v-else>连接信息读取中…</small>
        </div>
        <div class="engine-actions">
          <button v-if="canManage && storage?.legacyMysqlCount > 0" class="plain-btn" type="button" :disabled="migrating" @click="migrate">
            {{ migrating ? '迁移中…' : '迁移历史数据' }}
          </button>
          <button class="plain-btn" type="button" :disabled="loadingRows || loadingStats" @click="refreshAll">
            <SyncOutlined /> 刷新
          </button>
        </div>
      </section>
      <p v-if="storageMessage" class="engine-message">{{ storageMessage }}</p>

      <!-- 筛选 -->
      <section class="view-card">
        <div class="card-head">
          <div>
            <h2 class="view-card__title"><FilterOutlined /> 筛选条件</h2>
            <p class="hint">时间范围、指标区间、闸门状态与异常记录可任意组合</p>
          </div>
          <button class="link-btn" type="button" @click="advanced = !advanced">{{ advanced ? '收起高级筛选' : '展开高级筛选' }}</button>
        </div>
        <form class="filter-form" @submit.prevent="applyFilters">
          <div class="filter-row">
            <label>开始时间<input v-model="filters.start" type="datetime-local" /></label>
            <label>结束时间<input v-model="filters.end" type="datetime-local" /></label>
            <label>排序
              <select v-model="filters.sort">
                <option value="desc">最新在前</option>
                <option value="asc">最早在前</option>
              </select>
            </label>
            <label class="check-label"><input v-model="filters.abnormal" type="checkbox" /> 只看超出阈值</label>
          </div>

          <div v-if="advanced" class="filter-row range-row">
            <div v-for="metric in metricDefs" :key="metric.key" class="range-group">
              <span>{{ metric.label }}</span>
              <input v-model="filters[metric.minKey]" type="number" step="any" :placeholder="`最小${metric.unit ? '（' + metric.unit + '）' : ''}`" />
              <input v-model="filters[metric.maxKey]" type="number" step="any" :placeholder="`最大${metric.unit ? '（' + metric.unit + '）' : ''}`" />
            </div>
          </div>

          <div v-if="advanced" class="gate-row">
            <span class="gate-label">闸门状态</span>
            <label v-for="(_, index) in filters.gates" :key="index">闸门{{ index + 1 }}
              <select v-model="filters.gates[index]">
                <option value="">不限</option>
                <option value="1">开</option>
                <option value="0">关</option>
              </select>
            </label>
          </div>

          <div class="filter-actions">
            <button class="primary-btn" type="submit">查询</button>
            <button class="plain-btn" type="button" @click="resetFilters">重置</button>
            <button class="plain-btn" type="button" :disabled="exporting" @click="exportCsv">{{ exporting ? '导出中…' : '导出 CSV' }}</button>
            <span class="filter-note">导出上限 10000 条，按当前筛选条件生成</span>
          </div>
        </form>
      </section>

      <div v-if="error" class="alert-error" role="alert">{{ error }}</div>

      <!-- 统计卡片 -->
      <section class="stat-grid">
        <article class="stat-card">
          <span>记录总数</span>
          <strong>{{ count }}<small>条</small></strong>
          <em>{{ rangeHint }}</em>
        </article>
        <article class="stat-card">
          <span>平均水位</span>
          <strong>{{ show(levelStat?.avg, levelStat?.digits) }}<small>m</small></strong>
          <em>阈值 {{ thresholdText(levelStat) }}</em>
        </article>
        <article class="stat-card">
          <span>水位峰值</span>
          <strong>{{ show(levelStat?.max, levelStat?.digits) }}<small>m</small></strong>
          <em>最低 {{ show(levelStat?.min, levelStat?.digits) }} m</em>
        </article>
        <article class="stat-card" :class="{ 'is-warn': abnormalCount > 0 }">
          <span>超阈值记录</span>
          <strong>{{ abnormalCount }}<small>条</small></strong>
          <em>占比 {{ abnormalRate }}%</em>
        </article>
        <article class="stat-card">
          <span>闸门开启记录</span>
          <strong>{{ gateOpenTotal }}<small>次</small></strong>
          <em>6 路闸门合计</em>
        </article>
      </section>

      <!-- 趋势 -->
      <section class="view-card trend-card">
        <div class="card-head">
          <div>
            <h2 class="view-card__title"><LineChartOutlined /> 水位趋势</h2>
            <p class="hint">按筛选范围分桶聚合，展示每个时间桶的平均水位</p>
          </div>
          <div class="segmented">
            <button type="button" :class="{ active: granularity === 'hour' }" @click="setGranularity('hour')">按小时</button>
            <button type="button" :class="{ active: granularity === 'day' }" @click="setGranularity('day')">按天</button>
          </div>
        </div>
        <template v-if="chart">
          <div class="trend-chart">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <defs>
                <linearGradient id="waterTrendFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stop-color="#2e9be8" stop-opacity=".3" />
                  <stop offset="100%" stop-color="#2e9be8" stop-opacity="0" />
                </linearGradient>
              </defs>
              <polygon :points="chart.area" fill="url(#waterTrendFill)" />
              <polyline :points="chart.polyline" fill="none" stroke="#2e9be8" stroke-width="1.6" vector-effect="non-scaling-stroke" />
            </svg>
            <i v-for="dot in chart.dots" :key="dot.label" class="trend-dot" :style="{ left: `${dot.x}%`, top: `${dot.y}%` }" :title="dot.title"></i>
            <span class="trend-max">峰值 {{ show(chart.max, 2) }} m</span>
            <span class="trend-min">谷值 {{ show(chart.min, 2) }} m</span>
          </div>
          <div class="trend-axis"><span v-for="label in chart.axis" :key="label">{{ label }}</span></div>
        </template>
        <p v-else class="empty">{{ loadingStats ? '正在统计…' : '当前筛选范围内没有可绘制的数据' }}</p>
      </section>

      <!-- 指标 + 闸门统计 -->
      <section class="stats-pair">
        <article class="view-card">
          <div class="card-head"><h2 class="view-card__title">指标统计</h2><span class="hint">越界按当前监测阈值判定</span></div>
          <div class="table-wrap">
            <table class="data-table compact">
              <thead><tr><th>指标</th><th>阈值范围</th><th>最小</th><th>平均</th><th>最大</th><th>越界</th></tr></thead>
              <tbody>
                <tr v-for="metric in metricStats" :key="metric.code">
                  <td><strong class="metric-name">{{ metric.name }}</strong><small class="unit">{{ metric.unit }}</small></td>
                  <td>{{ thresholdText(metric) }}</td>
                  <td>{{ show(metric.min, metric.digits) }}</td>
                  <td>{{ show(metric.avg, metric.digits) }}</td>
                  <td>{{ show(metric.max, metric.digits) }}</td>
                  <td><span class="state-badge" :class="metric.abnormalCount > 0 ? 'bad' : 'ok'">{{ metric.abnormalCount }}</span></td>
                </tr>
                <tr v-if="!metricStats.length"><td colspan="6" class="empty-cell">暂无统计结果</td></tr>
              </tbody>
            </table>
          </div>
        </article>

        <article class="view-card">
          <div class="card-head"><h2 class="view-card__title">闸门开启统计</h2><span class="hint">按筛选范围统计</span></div>
          <div class="gate-stats">
            <div v-for="gate in gateStats" :key="gate.index" class="gate-stat">
              <span class="gate-stat__label">闸门{{ gate.index }}</span>
              <div class="gate-stat__bar"><i :style="{ width: `${Math.round(gate.openRate * 100)}%` }"></i></div>
              <span class="gate-stat__value">{{ Math.round(gate.openRate * 100) }}%</span>
              <small>开 {{ gate.open }} / 关 {{ gate.closed }}</small>
            </div>
            <p v-if="!gateStats.length" class="empty">暂无数据</p>
          </div>
        </article>
      </section>

      <!-- 数据表 -->
      <section class="view-card">
        <div class="card-head">
          <div>
            <h2 class="view-card__title">水情记录</h2>
            <p class="hint">共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</p>
          </div>
          <label class="page-size">每页
            <select v-model.number="filters.size" @change="applyFilters">
              <option :value="20">20</option>
              <option :value="50">50</option>
              <option :value="100">100</option>
            </select>
            条
          </label>
        </div>
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr><th>采集时间</th><th>水位（m）</th><th>液温（℃）</th><th>pH</th><th>ORP（mV）</th><th>闸门状态</th><th>判定</th><th>来源</th></tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.id || row.time">
                <td class="nowrap">{{ formatTime(row.time) }}</td>
                <td :class="{ hot: isHot(row, 'level') }">{{ show(row.level) }}</td>
                <td :class="{ hot: isHot(row, 'temperature') }">{{ show(row.temperature) }}</td>
                <td :class="{ hot: isHot(row, 'ph') }">{{ show(row.ph) }}</td>
                <td :class="{ hot: isHot(row, 'orp') }">{{ show(row.orp) }}</td>
                <td>
                  <div class="gate-badges">
                    <i v-for="(state, index) in gateStates(row)" :key="index" :class="{ on: state === 1 }" :title="`闸门${index + 1}：${state === 1 ? '开' : '关'}`">{{ state === 1 ? '开' : '关' }}</i>
                  </div>
                </td>
                <td><span class="state-badge" :class="row.abnormal ? 'bad' : 'ok'">{{ row.abnormal ? '超限' : '正常' }}</span></td>
                <td class="source">{{ row.source === 'mysql-migration' ? '历史迁移' : 'MQTT' }}</td>
              </tr>
              <tr v-if="!rows.length">
                <td colspan="8" class="empty-cell">{{ loadingRows ? '正在读取 MongoDB…' : '当前筛选条件下没有记录' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="pagination">
          <span>共 {{ total }} 条 · 第 {{ page }} / {{ pages }} 页</span>
          <button class="plain-btn" type="button" :disabled="page <= 1 || loadingRows" @click="goPage(page - 1)">上一页</button>
          <button class="plain-btn" type="button" :disabled="page >= pages || loadingRows" @click="goPage(page + 1)">下一页</button>
        </div>
      </section>

      <!-- 清理 -->
      <section v-if="canManage" class="view-card clean-panel">
        <div class="card-head">
          <div>
            <h2 class="view-card__title"><DeleteOutlined /> 历史数据清理</h2>
            <p class="hint">删除 MongoDB 中指定时间之前的记录，建议先导出 CSV</p>
          </div>
        </div>
        <div class="clean-row">
          <input v-model="beforeTime" type="datetime-local" />
          <button class="danger-btn" type="button" @click="clean">清理历史数据</button>
          <span v-if="cleanMessage" class="success-tip">{{ cleanMessage }}</span>
        </div>
      </section>
    </div>
  </ViewShell>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { DatabaseOutlined, DeleteOutlined, FilterOutlined, LineChartOutlined, SyncOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import {
  cleanWaterLogs,
  exportWaterLogs,
  migrateWaterLogs,
  queryWaterLogs,
  waterStats,
  waterStorage,
} from '../api/manageApi.js'

const accountLevel = Number(localStorage.getItem('level') ?? 1)
const canManage = accountLevel === 0 || accountLevel >= 3

const metricDefs = [
  { key: 'level', label: '水位', unit: 'm', minKey: 'minLevel', maxKey: 'maxLevel' },
  { key: 'temperature', label: '液温', unit: '℃', minKey: 'minTemperature', maxKey: 'maxTemperature' },
  { key: 'ph', label: 'pH', unit: '', minKey: 'minPh', maxKey: 'maxPh' },
  { key: 'orp', label: 'ORP', unit: 'mV', minKey: 'minOrp', maxKey: 'maxOrp' },
]

const defaults = () => ({
  start: '', end: '',
  minLevel: '', maxLevel: '', minTemperature: '', maxTemperature: '',
  minPh: '', maxPh: '', minOrp: '', maxOrp: '',
  gates: ['', '', '', '', '', ''],
  abnormal: false,
  sort: 'desc',
  page: 1,
  size: 20,
})

const filters = reactive(defaults())
const rows = ref([])
const total = ref(0)
const stats = ref(null)
const storage = ref(null)
const storageMessage = ref('')
const error = ref('')
const cleanMessage = ref('')
const beforeTime = ref('')
const advanced = ref(false)
const granularity = ref('hour')
const loadingRows = ref(false)
const loadingStats = ref(false)
const exporting = ref(false)
const migrating = ref(false)

const count = computed(() => Number(stats.value?.count ?? total.value) || 0)
const page = computed(() => filters.page)
const pages = computed(() => Math.max(1, Math.ceil(total.value / filters.size)))
const storageOk = computed(() => storage.value?.reachable === true)
const abnormalCount = computed(() => Number(stats.value?.abnormalCount ?? 0))
const abnormalRate = computed(() => count.value ? ((abnormalCount.value / count.value) * 100).toFixed(1) : '0.0')
const metricStats = computed(() => stats.value?.metrics || [])
const gateStats = computed(() => stats.value?.gates || [])
const levelStat = computed(() => metricStats.value.find((metric) => metric.code === 'water_level') || null)
const gateOpenTotal = computed(() => gateStats.value.reduce((sum, gate) => sum + Number(gate.open || 0), 0))
const rangeHint = computed(() => {
  if (!filters.start && !filters.end) return '全部时间范围'
  const from = filters.start ? filters.start.replace('T', ' ') : '最早'
  const to = filters.end ? filters.end.replace('T', ' ') : '至今'
  return `${from} ~ ${to}`
})

const chart = computed(() => {
  const buckets = stats.value?.buckets || []
  const points = buckets
    .map((bucket) => ({ ...bucket, value: Number(bucket.avgLevel) }))
    .filter((bucket) => Number.isFinite(bucket.value))
  if (!points.length) return null
  const values = points.map((point) => point.value)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = max - min || 1
  const dots = points.map((point, index) => ({
    label: point.label,
    x: points.length === 1 ? 50 : 3 + (index / (points.length - 1)) * 94,
    y: 92 - ((point.value - min) / spread) * 78,
    title: `${point.label} · 平均 ${point.value.toFixed(2)} m · ${point.count} 条`,
  }))
  const polyline = dots.map((dot) => `${dot.x},${dot.y}`).join(' ')
  const axis = dots.length <= 3 ? dots : [dots[0], dots[Math.floor((dots.length - 1) / 2)], dots[dots.length - 1]]
  return {
    dots,
    polyline,
    axis: axis.map((dot) => dot.label),
    area: `${polyline} 100,100 0,100`,
    min,
    max,
  }
})

const show = (value, digits = 2) => (value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits))
const formatTime = (value) => (value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '—')
const thresholdText = (metric) => {
  if (!metric) return '—'
  const low = metric.low === null || metric.low === undefined ? '—' : metric.low
  const high = metric.high === null || metric.high === undefined ? '—' : metric.high
  if (low === '—' && high === '—') return '未配置'
  return `${low} ~ ${high}${metric.unit ? ` ${metric.unit}` : ''}`
}
const isHot = (row, field) => Array.isArray(row.abnormalMetrics) && row.abnormalMetrics.includes(field)
const gateStates = (row) => Array.from({ length: 6 }, (_, index) => Number(row[`relay${index + 1}`]) || 0)

async function loadRows() {
  loadingRows.value = true
  error.value = ''
  try {
    const result = await queryWaterLogs(filters, { page: filters.page, size: filters.size })
    const data = result.data || {}
    rows.value = data.rows || []
    total.value = Number(data.total || 0)
  } catch (e) {
    error.value = e.message
    rows.value = []
    total.value = 0
  } finally {
    loadingRows.value = false
  }
}

async function loadStats() {
  loadingStats.value = true
  try {
    const result = await waterStats(filters, granularity.value)
    stats.value = result.data || null
  } catch (e) {
    stats.value = null
    if (!error.value) error.value = e.message
  } finally {
    loadingStats.value = false
  }
}

async function loadStorage() {
  try {
    storage.value = (await waterStorage()).data || null
    storageMessage.value = storage.value?.message || ''
  } catch (e) {
    storage.value = null
    storageMessage.value = e.message
  }
}

async function refreshAll() {
  await Promise.allSettled([loadStorage(), loadRows(), loadStats()])
}

function applyFilters() {
  filters.page = 1
  // 统计卡片与趋势图也必须跟着筛选条件走，否则会出现「表格 2 条、卡片还是 10 条」
  void Promise.allSettled([loadRows(), loadStats()])
}

function resetFilters() {
  Object.assign(filters, defaults())
  void refreshAll()
}

function goPage(target) {
  if (target < 1 || target > pages.value) return
  filters.page = target
  void loadRows()
}

function setGranularity(value) {
  if (granularity.value === value) return
  granularity.value = value
  void loadStats()
}

async function exportCsv() {
  exporting.value = true
  error.value = ''
  try {
    await exportWaterLogs(filters)
  } catch (e) {
    error.value = e.message
  } finally {
    exporting.value = false
  }
}

async function migrate() {
  if (!window.confirm('把旧 MySQL 表 water_log 的历史数据迁移到 MongoDB？可重复执行，不会产生重复记录。')) return
  migrating.value = true
  error.value = ''
  try {
    const result = (await migrateWaterLogs()).data || {}
    storageMessage.value = `迁移完成：读取 ${result.read ?? 0} 条，写入 ${result.inserted ?? 0} 条，跳过 ${result.skipped ?? 0} 条（${result.elapsedMs ?? 0} ms）`
    await refreshAll()
  } catch (e) {
    error.value = e.message
  } finally {
    migrating.value = false
  }
}

async function clean() {
  if (!beforeTime.value) {
    error.value = '请先选择清理时间'
    return
  }
  if (!window.confirm('确认清理该时间之前的水情记录吗？此操作不可恢复。')) return
  error.value = ''
  try {
    const result = await cleanWaterLogs(beforeTime.value)
    cleanMessage.value = result.message || '历史数据已清理'
    filters.page = 1
    await refreshAll()
  } catch (e) {
    error.value = e.message
  }
}

onMounted(() => { void refreshAll() })
</script>

<style scoped>
.data-page{display:flex;flex-direction:column;gap:14px;min-width:0}
.engine-bar{display:flex;align-items:center;gap:12px;padding:12px 16px;border:1px solid #e2ebf3;border-radius:12px;background:#fbfdfe}
.engine-bar.is-online{border-color:#cfe9df;background:#f6fcf9}
.engine-bar.is-offline{border-color:#f2d9d6;background:#fff8f7}
.engine-dot{width:9px;height:9px;flex:0 0 9px;border-radius:50%;background:#d2a24d}
.engine-bar.is-online .engine-dot{background:#2ac49a;box-shadow:0 0 0 4px rgba(42,196,154,.12)}
.engine-bar.is-offline .engine-dot{background:#d95c54;box-shadow:0 0 0 4px rgba(217,92,84,.12)}
.engine-copy{flex:1;min-width:0}
.engine-copy strong,.engine-copy small{display:block}
.engine-copy strong{color:#294b66;font-size:12px}
.engine-copy small{margin-top:3px;color:#8499a8;font-size:10px}
.engine-actions{display:flex;gap:8px}
.engine-message{margin:-6px 0 0;color:#6b7f90;font-size:11px}
.view-card{padding:16px;border:1px solid #e2ebf3;border-radius:15px;background:rgba(255,255,255,.94);box-shadow:0 8px 22px rgba(31,80,117,.06)}
.view-card__title{display:flex;align-items:center;gap:8px;margin:0;color:#1b3e5c;font-size:14px;font-weight:650}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:16px;margin-bottom:14px}
.card-head .view-card__title{display:flex;align-items:center;gap:6px;margin:0}
.hint{margin:4px 0 0;color:#8b9daa;font-size:10px}
.link-btn{border:0;background:none;color:#1679d1;font-size:11px;cursor:pointer;padding:2px 0}
.filter-form{display:flex;flex-direction:column;gap:12px}
.filter-row{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px}
.filter-row label{display:grid;gap:4px;color:#7890a4;font-size:11px}
.filter-row input[type='datetime-local'],.filter-row input[type='number'],.filter-row select,.clean-row input{height:34px;border:1px solid #dce8f0;border-radius:7px;padding:0 8px;color:#355571;font-size:11px;background:#fff}
.filter-row input[type='number']{width:96px}
.filter-row select{min-width:110px}
.check-label{display:flex!important;align-items:center;gap:6px;height:34px;color:#557188;font-size:11px;cursor:pointer}
.check-label input{width:14px;height:14px;accent-color:#1679d1}
.range-row{gap:18px}
.range-group{display:flex;align-items:center;gap:6px}
.range-group>span{color:#617b90;font-size:11px;min-width:34px}
.gate-row{display:flex;flex-wrap:wrap;align-items:center;gap:10px;padding-top:10px;border-top:1px dashed #e6eef4}
.gate-label{color:#617b90;font-size:11px}
.gate-row label{display:flex;align-items:center;gap:4px;color:#7890a4;font-size:10px}
.gate-row select{height:30px;border:1px solid #dce8f0;border-radius:6px;color:#557188;font-size:10px;background:#fff}
.filter-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.filter-note{color:#93a5b4;font-size:10px}
.primary-btn,.plain-btn,.danger-btn{height:34px;padding:0 14px;border-radius:8px;font-size:12px;cursor:pointer;display:inline-flex;align-items:center;gap:5px}
.primary-btn{border:0;background:#1679d1;color:#fff}
.plain-btn{border:1px solid #d8e5ee;background:#fff;color:#557188}
.plain-btn:disabled,.danger-btn:disabled,.primary-btn:disabled{opacity:.5;cursor:not-allowed}
.danger-btn{border:1px solid #f0c4c1;background:#fff5f4;color:#c25854}
.alert-error{padding:10px 14px;border-radius:8px;background:#fff2f1;color:#b64c4a;font-size:12px}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px}
.stat-card{padding:14px 16px;border:1px solid #e2ebf3;border-radius:12px;background:#fff;box-shadow:0 6px 18px rgba(31,80,117,.05)}
.stat-card>span{display:block;color:#8499a8;font-size:10px}
.stat-card strong{display:block;margin:6px 0 2px;color:#1d5679;font-size:23px;line-height:1.1}
.stat-card strong small{margin-left:4px;color:#8b9daa;font-size:10px;font-weight:500}
.stat-card em{color:#8fa2b1;font-size:10px;font-style:normal}
.stat-card.is-warn{border-color:#f2d9d6;background:#fff9f8}
.stat-card.is-warn strong{color:#c25854}
.trend-card{min-height:240px}
.segmented{display:inline-flex;border:1px solid #dce8f0;border-radius:8px;overflow:hidden}
.segmented button{height:28px;padding:0 12px;border:0;background:#fff;color:#7890a4;font-size:11px;cursor:pointer}
.segmented button.active{background:#eaf4fd;color:#1679d1;font-weight:600}
.trend-chart{position:relative;height:170px;border-radius:8px;background:repeating-linear-gradient(to bottom,transparent 0 34px,#f1f6fa 35px)}
.trend-chart svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.trend-dot{position:absolute;width:7px;height:7px;transform:translate(-50%,-50%);border:2px solid #fff;border-radius:50%;background:#2e9be8;box-shadow:0 0 0 1px #2e9be8}
.trend-max,.trend-min{position:absolute;left:6px;padding:2px 6px;border-radius:5px;background:rgba(255,255,255,.85);color:#7b8fa0;font-size:9px}
.trend-max{top:4px}
.trend-min{bottom:4px}
.trend-axis{display:flex;justify-content:space-between;gap:8px;margin-top:8px;color:#93a5b4;font-size:9px}
.trend-axis span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.empty,.empty-cell{padding:26px 12px;color:#91a4b2;font-size:11px;text-align:center}
.stats-pair{display:grid;grid-template-columns:1.35fr 1fr;gap:14px}
.table-wrap{overflow:auto}
.data-table{width:100%;border-collapse:collapse;color:#557188;font-size:11px}
.data-table th{padding:10px;background:#f5f9fb;color:#8198aa;font-weight:600;text-align:left;white-space:nowrap}
.data-table td{padding:10px;border-bottom:1px solid #edf2f5;white-space:nowrap}
.data-table.compact td,.data-table.compact th{padding:9px 8px}
.data-table td.hot{color:#c25854;font-weight:700;background:#fff7f6}
.data-table .nowrap{white-space:nowrap}
.metric-name{color:#315571;font-size:11px}
.unit{margin-left:3px;color:#93a5b4;font-size:9px}
.gate-badges{display:flex;gap:3px}
.gate-badges i{display:inline-flex;align-items:center;justify-content:center;width:17px;height:17px;border-radius:4px;background:#eff4f7;color:#8a9daa;font-size:9px;font-style:normal}
.gate-badges i.on{background:#e8faf3;color:#168b69;font-weight:600}
.state-badge{display:inline-flex;align-items:center;justify-content:center;min-width:38px;padding:2px 7px;border-radius:9px;font-size:10px}
.state-badge.ok{background:#e8faf3;color:#168b69}
.state-badge.bad{background:#fff1ef;color:#c25854;font-weight:600}
.source{color:#93a5b4;font-size:10px}
.gate-stats{display:flex;flex-direction:column;gap:10px}
.gate-stat{display:grid;grid-template-columns:44px 1fr 38px 88px;align-items:center;gap:8px}
.gate-stat__label{color:#557188;font-size:11px}
.gate-stat__bar{height:7px;border-radius:5px;background:#edf3f7;overflow:hidden}
.gate-stat__bar i{display:block;height:100%;border-radius:5px;background:linear-gradient(90deg,#4bb7ef,#1679d1)}
.gate-stat__value{color:#1d5679;font-size:11px;text-align:right}
.gate-stat small{color:#93a5b4;font-size:9px}
.pagination{display:flex;justify-content:flex-end;align-items:center;gap:10px;margin-top:14px;color:#7890a4;font-size:11px}
.page-size{display:flex;align-items:center;gap:5px;color:#7890a4;font-size:11px}
.page-size select{height:28px;border:1px solid #dce8f0;border-radius:6px;color:#557188;font-size:11px;background:#fff}
.clean-panel .clean-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.success-tip{color:#168b69;font-size:11px}
@media (max-width:1280px){.stats-pair{grid-template-columns:1fr}}
@media (max-width:820px){.engine-bar{flex-wrap:wrap}}
</style>
