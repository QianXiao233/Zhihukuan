<template>
  <ViewShell title="告警中心" :tag="headerTag" :icon="AlertOutlined">
    <div class="ac-page">
      <section class="ac-summary">
        <article v-for="item in summaryCards" :key="item.key" class="ac-summary__card" :class="`is-${item.tone}`">
          <span class="ac-summary__icon"><component :is="item.icon" /></span>
          <div>
            <small>{{ item.label }}</small>
            <strong>{{ item.value }}<i v-if="item.unit">{{ item.unit }}</i></strong>
            <em>{{ item.hint }}</em>
          </div>
        </article>
      </section>

      <section class="ac-live" :class="{ 'has-violation': violations.length, 'has-error': !serverStatus && error }">
        <div class="ac-live__head">
          <span class="ac-live__icon"><ThunderboltOutlined /></span>
          <div>
            <strong>{{ liveTitle }}</strong>
            <small>{{ liveHint }}</small>
          </div>
          <button type="button" class="ac-ghost" :disabled="refreshing" @click="refresh">
            <ReloadOutlined :class="{ 'is-spinning': refreshing }" />{{ refreshing ? '刷新中' : '刷新' }}
          </button>
        </div>
        <div v-if="violations.length" class="ac-live__chips">
          <span v-for="item in violations" :key="item.code">
            <b>{{ item.name || item.code }}</b>
            {{ item.value ?? '—' }}{{ item.unit || '' }}
            <i>{{ item.direction || '越界' }}</i>
          </span>
        </div>
      </section>

      <p v-if="error && serverStatus" class="ac-error">{{ error }}</p>

      <section class="ac-layout">
        <article class="ac-card ac-card--table">
          <header class="ac-card__head">
            <div><span class="ac-card__icon"><HistoryOutlined /></span><h2>告警记录</h2><span class="ac-chip">最近 {{ filteredAlerts.length }} / {{ recentAlerts.length }} 条</span></div>
            <span class="ac-updated">{{ refreshedAt === '—' ? '正在读取' : `更新于 ${refreshedAt}` }}</span>
          </header>

          <div class="ac-filters">
            <label>
              <span>监测指标</span>
              <select v-model="metricFilter">
                <option value="all">全部指标</option>
                <option v-for="option in METRIC_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
            </label>
            <label>
              <span>推送状态</span>
              <select v-model="statusFilter">
                <option value="all">全部状态</option>
                <option value="sent">已推送</option>
                <option value="queued">推送中</option>
                <option value="failed">推送失败</option>
                <option value="skipped">未推送</option>
              </select>
            </label>
            <button type="button" class="ac-reset" @click="resetFilters">重置筛选</button>
          </div>

          <div v-if="alertsLoading" class="ac-empty">正在读取告警记录…</div>
          <div v-else-if="error && !recentAlerts.length" class="ac-empty">告警记录读取失败：{{ error }}</div>
          <div v-else-if="!recentAlerts.length" class="ac-empty">暂无告警记录。当读数超出阈值时，记录会自动出现在这里。</div>
          <div v-else-if="!filteredAlerts.length" class="ac-empty">没有符合当前筛选条件的告警。</div>
          <div v-else class="ac-table-wrap">
            <table class="ac-table">
              <thead>
                <tr><th>时间</th><th>监测指标</th><th>读数</th><th>阈值区间</th><th>方向</th><th>推送状态</th></tr>
              </thead>
              <tbody>
                <tr v-for="item in filteredAlerts" :key="item.id ?? `${item.time}-${item.metric}`">
                  <td class="ac-time">{{ item.timeText || '—' }}</td>
                  <td><strong>{{ item.metricName || metricLabel(item.metric) }}</strong></td>
                  <td><b class="ac-value">{{ item.value ?? '—' }}</b><small>{{ item.unit || '' }}</small></td>
                  <td>{{ item.low ?? '—' }} ~ {{ item.high ?? '—' }}</td>
                  <td><span class="ac-direction" :class="directionTone(item.direction)">{{ item.direction || '—' }}</span></td>
                  <td><span class="ac-push" :class="pushTone(item.status)">{{ pushText(item.status) }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </article>

        <aside class="ac-side">
          <article class="ac-card">
            <header class="ac-card__head">
              <div><span class="ac-card__icon ac-card__icon--green"><SendOutlined /></span><h2>推送通道</h2></div>
            </header>
            <div class="ac-channel" :class="`is-${pushState.tone}`">
              <span><i></i>{{ pushState.label }}</span>
              <strong>{{ pushState.desc }}</strong>
            </div>
            <div class="ac-channel-list">
              <div><span>告警开关</span><b :class="alertFlags.known ? (alertFlags.alertEnabled ? 'on' : 'off') : ''">{{ alertFlags.known ? (alertFlags.alertEnabled ? '已启用' : '已停用') : '—' }}</b></div>
              <div><span>对外推送</span><b :class="alertFlags.known ? (alertFlags.pushEnabled ? 'on' : 'off') : ''">{{ alertFlags.known ? (alertFlags.pushEnabled ? '已启用' : '已停用') : '—' }}</b></div>
              <div><span>推送 Token</span><b :class="alertFlags.known ? (alertFlags.tokenConfigured ? 'on' : 'off') : ''">{{ alertFlags.known ? (alertFlags.tokenConfigured ? '已配置' : '未配置') : '—' }}</b></div>
              <div><span>冷却时间</span><b>{{ alertFlags.known ? `${alertFlags.cooldownMinutes} 分钟` : '—' }}</b></div>
              <div><span>本轮抑制</span><b>{{ alertFlags.known ? `${alertFlags.suppressedCount} 次` : '—' }}</b></div>
            </div>

            <div v-if="cooldownItems.length" class="ac-cooldown">
              <span>冷却中的指标</span>
              <div v-for="item in cooldownItems" :key="item.key"><i></i>{{ item.label }}<b>{{ item.minutes }} 分钟</b></div>
            </div>

            <button type="button" class="ac-primary" @click="go('settings')"><SettingOutlined /> 前往推送设置</button>
          </article>

          <article class="ac-card ac-card--quick">
            <header class="ac-card__head">
              <div><span class="ac-card__icon"><AppstoreOutlined /></span><h2>关联页面</h2></div>
            </header>
            <button v-for="link in SIDE_LINKS" :key="link.name" type="button" class="ac-quick" @click="go(link.name)">
              <span><component :is="link.icon" /></span>
              <div><strong>{{ link.title }}</strong><small>{{ link.desc }}</small></div>
              <RightOutlined />
            </button>
          </article>
        </aside>
      </section>
    </div>
  </ViewShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertOutlined,
  AppstoreOutlined,
  BellOutlined,
  CheckCircleOutlined,
  ControlOutlined,
  DashboardOutlined,
  HistoryOutlined,
  ReloadOutlined,
  RightOutlined,
  SendOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { monitorStatus } from '../api/manageApi.js'

const router = useRouter()
const serverStatus = ref(null)
const loading = ref(true)
const refreshing = ref(false)
const error = ref('')
const refreshedAt = ref('—')
const metricFilter = ref('all')
const statusFilter = ref('all')
let refreshTimer

const METRIC_OPTIONS = [
  { value: 'water_level', label: '水位' },
  { value: 'temperature', label: '液温' },
  { value: 'ph', label: 'pH' },
  { value: 'orp', label: 'ORP' },
]

const violations = computed(() => serverStatus.value?.violations || [])
const recentAlerts = computed(() => serverStatus.value?.recentAlerts || [])
const alertsLoading = computed(() => loading.value && !serverStatus.value)

function metricLabel(code) {
  const normalized = String(code || '').toLowerCase()
  return METRIC_OPTIONS.find((option) => option.value === normalized || (option.value === 'water_level' && normalized === 'level') || (option.value === 'temperature' && normalized === 'temp'))?.label || code || '—'
}

function normalizeMetric(code) {
  const normalized = String(code || '').toLowerCase()
  if (normalized === 'level') return 'water_level'
  if (normalized === 'temp') return 'temperature'
  return normalized
}

const filteredAlerts = computed(() => recentAlerts.value.filter((item) => {
  if (metricFilter.value !== 'all' && normalizeMetric(item.metric) !== metricFilter.value) return false
  if (statusFilter.value === 'all') return true
  if (statusFilter.value === 'skipped') return !['sent', 'queued', 'failed'].includes(item.status)
  return item.status === statusFilter.value
}))

const pushState = computed(() => {
  const alert = serverStatus.value?.alert
  if (!alert) return { tone: 'pending', label: '读取中', desc: error.value || '正在读取推送配置' }
  if (!alert.alertEnabled) return { tone: 'off', label: '告警已停用', desc: '实时阈值监控关闭，不会产生新告警' }
  if (!alert.pushEnabled) return { tone: 'off', label: '推送已关闭', desc: '告警仍会记录，但不会对外发送' }
  if (!alert.tokenConfigured) return { tone: 'warn', label: '缺少 Token', desc: '配置推送 token 后才能外发告警' }
  return { tone: 'ok', label: '通道就绪', desc: '阈值越界后会按冷却策略推送' }
})

const alertFlags = computed(() => {
  const alert = serverStatus.value?.alert
  return {
    known: Boolean(alert),
    alertEnabled: alert?.alertEnabled !== false,
    pushEnabled: alert?.pushEnabled !== false,
    tokenConfigured: Boolean(alert?.tokenConfigured),
    cooldownMinutes: alert?.cooldownMinutes ?? '—',
    suppressedCount: alert?.suppressedCount ?? 0,
  }
})

const cooldownItems = computed(() => Object.entries(serverStatus.value?.alert?.cooldownRemaining || {})
  .filter(([, seconds]) => Number(seconds) > 0)
  .map(([key, seconds]) => ({
    key,
    label: metricLabel(String(key).replace('metric:', '')),
    minutes: Math.ceil(Number(seconds) / 60),
  })))

const summaryCards = computed(() => {
  const known = Boolean(serverStatus.value)
  const pushed = recentAlerts.value.filter((item) => item.status === 'sent').length
  const failed = recentAlerts.value.filter((item) => item.status === 'failed' || item.status === 'no-token').length
  return [
    { key: 'violations', label: '当前越界项', value: known ? violations.value.length : '—', unit: known ? '项' : '', hint: !known ? (error.value || '正在读取告警状态') : violations.value.length ? '需要立即关注的实时读数' : '实时读数均在阈值内', tone: !known ? 'muted' : violations.value.length ? 'danger' : 'ok', icon: ThunderboltOutlined },
    { key: 'recent', label: '近期告警记录', value: known ? recentAlerts.value.length : '—', unit: known ? '条' : '', hint: !known ? '告警记录暂未读取' : '来自后端阈值监控的最近记录', tone: known ? 'info' : 'muted', icon: BellOutlined },
    { key: 'pushed', label: '已成功推送', value: known ? pushed : '—', unit: known ? '条' : '', hint: !known ? '推送状态暂未读取' : failed ? `${failed} 条推送失败或缺少 Token` : '告警已送达推送通道', tone: !known ? 'muted' : failed ? 'warn' : 'ok', icon: CheckCircleOutlined },
    { key: 'suppressed', label: '冷却抑制', value: known ? alertFlags.value.suppressedCount : '—', unit: known ? '次' : '', hint: !known ? '冷却状态暂未读取' : `同一指标 ${alertFlags.value.cooldownMinutes} 分钟内只推一次`, tone: 'muted', icon: ControlOutlined },
  ]
})

const liveTitle = computed(() => {
  if (!serverStatus.value) return error.value ? '告警状态暂不可用' : '正在读取后端告警状态'
  if (violations.value.length) return `当前 ${violations.value.length} 项读数超出阈值`
  return '当前实时读数均在阈值内'
})

const liveHint = computed(() => {
  if (error.value) return error.value
  if (!serverStatus.value) return '正在读取后端监控状态'
  if (violations.value.length) return '受影响的读数已记录在下方告警列表，并按冷却策略推送'
  return `后端最近一次评估 ${serverStatus.value.alert?.lastEvaluatedAt ? '已完成' : '尚未执行'}，冷却 ${alertFlags.value.cooldownMinutes} 分钟`
})

const headerTag = computed(() => {
  if (error.value) return '告警状态读取失败'
  if (!serverStatus.value) return '读取告警状态'
  return violations.value.length ? `${violations.value.length} 项实时越界` : '当前无实时越界'
})

const SIDE_LINKS = [
  { name: 'monitor-detail', title: '实时监测', desc: '查看 RTU 实时读数与阈值', icon: DashboardOutlined },
  { name: 'monitoring-center', title: '监控中心', desc: '返回监控总览大屏', icon: AppstoreOutlined },
]

function pushText(status) {
  return ({ sent: '已推送', queued: '推送中', failed: '推送失败', skipped: '未推送', 'no-token': '缺 Token' })[status] || status || '—'
}

function pushTone(status) {
  if (status === 'sent') return 'ok'
  if (status === 'queued') return 'info'
  if (status === 'failed' || status === 'no-token') return 'danger'
  return 'muted'
}

function directionTone(direction) {
  const text = String(direction || '')
  if (text.includes('高') || text.includes('超')) return 'up'
  if (text.includes('低')) return 'down'
  return 'muted'
}

function resetFilters() {
  metricFilter.value = 'all'
  statusFilter.value = 'all'
}

function go(name) {
  void router.push({ name })
}

async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    serverStatus.value = (await monitorStatus()).data || null
    error.value = ''
    refreshedAt.value = new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
  } catch (e) {
    error.value = e.message || '告警状态读取失败'
  } finally {
    loading.value = false
    refreshing.value = false
  }
}

onMounted(() => {
  void refresh()
  refreshTimer = window.setInterval(refresh, 20000)
})
onBeforeUnmount(() => {
  if (refreshTimer) window.clearInterval(refreshTimer)
})
</script>

<style scoped>
.ac-page { display: flex; flex-direction: column; gap: 15px; min-width: 960px; }

.ac-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 13px; }
.ac-summary__card { display: flex; align-items: center; gap: 12px; padding: 15px 16px; border: 1px solid #e2ebf3; border-radius: 14px; background: rgba(255,255,255,.94); box-shadow: 0 7px 18px rgba(31,80,117,.055); }
.ac-summary__icon { display: inline-flex; align-items: center; justify-content: center; width: 38px; height: 38px; flex: 0 0 38px; border-radius: 11px; background: #eaf5ff; color: #2b87dd; font-size: 17px; }
.ac-summary__card.is-danger .ac-summary__icon { background: #fff0ef; color: #d75f57; }
.ac-summary__card.is-ok .ac-summary__icon { background: #e8fbf2; color: #1fa97c; }
.ac-summary__card.is-warn .ac-summary__icon { background: #fff4e4; color: #d99535; }
.ac-summary__card.is-muted .ac-summary__icon { background: #f1f5f8; color: #8499a9; }
.ac-summary__card > div { min-width: 0; }
.ac-summary__card small { display: block; color: #8197a8; font-size: 10px; }
.ac-summary__card strong { display: block; margin: 4px 0 3px; color: #173956; font-size: 24px; line-height: 1; font-weight: 700; }
.ac-summary__card strong i { margin-left: 3px; color: #7c92a3; font-size: 10px; font-style: normal; font-weight: 500; }
.ac-summary__card em { display: block; overflow: hidden; color: #93a5b4; font-size: 9px; font-style: normal; text-overflow: ellipsis; white-space: nowrap; }

.ac-live { padding: 13px 16px; border: 1px solid #d9eee4; border-radius: 13px; background: #f5fcf9; }
.ac-live.has-violation { border-color: #f2d9d6; background: #fff8f7; }
.ac-live.has-error { border-color: #efe2cc; background: #fffbf4; }
.ac-live.has-error .ac-live__icon { background: #fff4e4; color: #d99535; }
.ac-live__head { display: flex; align-items: center; gap: 11px; }
.ac-live__icon { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; flex: 0 0 30px; border-radius: 9px; background: #e8faf3; color: #168b69; font-size: 15px; }
.ac-live.has-violation .ac-live__icon { background: #ffeceb; color: #c25854; }
.ac-live__head > div { flex: 1; min-width: 0; }
.ac-live__head strong, .ac-live__head small { display: block; }
.ac-live__head strong { color: #294b66; font-size: 13px; }
.ac-live__head small { margin-top: 3px; color: #8a9daa; font-size: 10px; }
.ac-ghost { display: inline-flex; align-items: center; gap: 5px; height: 30px; padding: 0 11px; border: 1px solid #d8e5ee; border-radius: 8px; background: #fff; color: #557188; font: inherit; font-size: 10px; cursor: pointer; }
.ac-ghost:hover:not(:disabled) { border-color: #a9cee6; color: #1d78bd; }
.ac-ghost:disabled { opacity: .65; cursor: progress; }
.ac-live__chips { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 10px; padding-top: 10px; border-top: 1px dashed #f0dad7; }
.ac-live__chips > span { display: inline-flex; align-items: center; gap: 5px; padding: 4px 9px; border-radius: 8px; background: #fff1ef; color: #a94d49; font-size: 10px; }
.ac-live__chips b { font-weight: 600; }
.ac-live__chips i { padding-left: 5px; border-left: 1px solid #ecc9c5; color: #bf6d67; font-style: normal; }
.ac-error { margin: 0; padding: 9px 12px; border-radius: 8px; background: #fff2f1; color: #b64c4a; font-size: 11px; }

.ac-layout { display: grid; grid-template-columns: minmax(0, 2.35fr) minmax(300px, .95fr); gap: 15px; align-items: start; }
.ac-card { min-width: 0; padding: 15px 16px; border: 1px solid #e2ebf3; border-radius: 15px; background: rgba(255,255,255,.94); box-shadow: 0 8px 22px rgba(31,80,117,.06); }
.ac-card__head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 13px; }
.ac-card__head > div { display: flex; align-items: center; gap: 8px; min-width: 0; }
.ac-card__head h2 { margin: 0; color: #1b3e5c; font-size: 14px; font-weight: 650; white-space: nowrap; }
.ac-card__icon { display: inline-flex; align-items: center; justify-content: center; width: 25px; height: 25px; border-radius: 8px; background: #e9f4ff; color: #2985df; font-size: 13px; }
.ac-card__icon--green { background: #e8fbf2; color: #21a879; }
.ac-chip { padding: 3px 7px; border-radius: 9px; background: #f0f6fa; color: #7c93a6; font-size: 9px; white-space: nowrap; }
.ac-updated { color: #9aabb9; font-size: 9px; white-space: nowrap; }

.ac-filters { display: flex; align-items: flex-end; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; padding: 10px 12px; border: 1px solid #eaf0f4; border-radius: 10px; background: #fbfdfe; }
.ac-filters label { display: flex; flex-direction: column; gap: 4px; }
.ac-filters label > span { color: #7e95a7; font-size: 9px; }
.ac-filters select { height: 30px; min-width: 118px; padding: 0 8px; border: 1px solid #dce8f0; border-radius: 7px; background: #fff; color: #355571; font: inherit; font-size: 10px; outline: none; }
.ac-filters select:focus { border-color: #8fc4e8; }
.ac-reset { height: 30px; padding: 0 10px; border: 0; border-radius: 7px; background: #eef5fa; color: #64829a; font: inherit; font-size: 10px; cursor: pointer; }
.ac-reset:hover { background: #e3f0f9; color: #2f7fb8; }

.ac-table-wrap { overflow: auto; }
.ac-table { width: 100%; border-collapse: collapse; color: #557188; font-size: 11px; }
.ac-table th { padding: 9px 9px; color: #8299aa; background: #f6f9fb; font-weight: 600; text-align: left; white-space: nowrap; }
.ac-table td { padding: 10px 9px; border-bottom: 1px solid #edf2f5; white-space: nowrap; }
.ac-table tr:last-child td { border-bottom: 0; }
.ac-table tbody tr:hover { background: #fbfdff; }
.ac-time { color: #8096a7; font-variant-numeric: tabular-nums; }
.ac-table strong { color: #315571; font-weight: 600; }
.ac-value { color: #274c69; font-size: 12px; }
.ac-table small { margin-left: 2px; color: #93a5b4; font-size: 9px; }
.ac-direction { padding: 3px 7px; border-radius: 8px; background: #f1f5f8; color: #7b91a3; font-size: 9px; }
.ac-direction.up { background: #fff1ef; color: #bf5a55; }
.ac-direction.down { background: #eaf5ff; color: #2d7fc1; }
.ac-push { padding: 3px 8px; border-radius: 8px; font-size: 9px; }
.ac-push.ok { background: #e8faf3; color: #168b69; }
.ac-push.info { background: #eaf5ff; color: #2d7fc1; }
.ac-push.danger { background: #fff1ef; color: #bf5a55; }
.ac-push.muted { background: #f1f5f8; color: #7b91a3; }
.ac-empty { display: flex; align-items: center; justify-content: center; min-height: 190px; padding: 0 16px; color: #91a4b2; font-size: 11px; line-height: 1.8; text-align: center; }

.ac-side { display: flex; flex-direction: column; gap: 15px; }
.ac-channel { padding: 11px 12px; border: 1px solid #e5eef4; border-radius: 10px; background: #fbfdfe; }
.ac-channel > span { display: flex; align-items: center; gap: 6px; color: #527089; font-size: 11px; font-weight: 600; }
.ac-channel > span i { width: 7px; height: 7px; border-radius: 50%; background: #b7c5d0; }
.ac-channel.is-ok { border-color: #d7eee4; background: #f5fcf9; }
.ac-channel.is-ok > span i { background: #25c395; box-shadow: 0 0 0 3px rgba(37,195,149,.12); }
.ac-channel.is-warn { border-color: #f1e1c8; background: #fffaf1; }
.ac-channel.is-warn > span i { background: #e0a144; }
.ac-channel.is-off > span i { background: #c2ccd5; }
.ac-channel > strong { display: block; margin-top: 5px; color: #8a9daa; font-size: 9px; font-weight: 400; line-height: 1.6; }
.ac-channel-list { display: flex; flex-direction: column; gap: 7px; margin-top: 12px; }
.ac-channel-list > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; color: #7e95a7; font-size: 10px; }
.ac-channel-list b { color: #587287; font-size: 10px; font-weight: 600; }
.ac-channel-list b.on { color: #168b69; }
.ac-channel-list b.off { color: #b57322; }
.ac-cooldown { margin-top: 12px; padding-top: 10px; border-top: 1px dashed #e8eff4; }
.ac-cooldown > span { color: #8b9ead; font-size: 9px; }
.ac-cooldown > div { display: flex; align-items: center; gap: 6px; margin-top: 6px; color: #6f8698; font-size: 10px; }
.ac-cooldown i { width: 5px; height: 5px; border-radius: 50%; background: #e0a144; }
.ac-cooldown b { margin-left: auto; color: #9b7a3d; font-weight: 500; }
.ac-primary { display: flex; align-items: center; justify-content: center; gap: 6px; width: 100%; height: 34px; margin-top: 14px; border: 0; border-radius: 8px; background: #1679d1; color: #fff; font: inherit; font-size: 11px; cursor: pointer; box-shadow: 0 6px 15px rgba(22,121,209,.18); }
.ac-primary:hover { background: #0f6dc3; }
.ac-card--quick .ac-card__head { margin-bottom: 10px; }
.ac-quick { display: flex; align-items: center; gap: 9px; width: 100%; padding: 9px 10px; border: 1px solid #eaf0f4; border-radius: 9px; background: #fbfdfe; color: inherit; font: inherit; text-align: left; cursor: pointer; transition: .16s ease; }
.ac-quick + .ac-quick { margin-top: 7px; }
.ac-quick:hover { border-color: #c8e2f2; background: #f6fbfe; }
.ac-quick > span { display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; flex: 0 0 28px; border-radius: 8px; background: #e9f4ff; color: #2985df; font-size: 13px; }
.ac-quick > div { min-width: 0; flex: 1; }
.ac-quick strong, .ac-quick small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ac-quick strong { color: #315571; font-size: 10px; font-weight: 600; }
.ac-quick small { margin-top: 2px; color: #96a8b6; font-size: 9px; }
.ac-quick > :deep(svg) { color: #a9bccb; font-size: 9px; }

.is-spinning { animation: ac-spin .8s linear infinite; }
@keyframes ac-spin { to { transform: rotate(360deg); } }

@media (max-width: 1360px) {
  .ac-layout { grid-template-columns: 1fr; }
  .ac-side { display: grid; grid-template-columns: 1fr 1fr; align-items: start; }
}
@media (max-width: 1100px) {
  .ac-page { min-width: 760px; }
  .ac-summary { grid-template-columns: repeat(2, 1fr); }
  .ac-side { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .ac-page { min-width: 0; gap: 10px; }
  .ac-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
  .ac-summary__card { padding: 11px; gap: 8px; }
  .ac-summary__icon { flex-basis: 32px; width: 32px; height: 32px; font-size: 14px; }
  .ac-summary__card strong { font-size: 20px; }
  .ac-layout { grid-template-columns: 1fr; gap: 10px; }
  .ac-side { grid-template-columns: 1fr; gap: 10px; }
  .ac-filters { flex-direction: column; align-items: stretch; }
  .ac-filters label, .ac-filters select { width: 100%; }
  .ac-reset { width: 100%; }
  .ac-live__head { flex-wrap: wrap; }
  .ac-ghost { margin-left: auto; }
  .ac-table { min-width: 620px; }
  .ac-updated { display: none; }
  .ac-card { padding: 13px; }
}
</style>
