<template>
  <ViewShell
    title="防汛调度"
    :tag="shellTag"
    :icon="ThunderboltOutlined"
  >
    <!-- ══════════ 水位与闸门总览 ══════════ -->
    <section class="brain-card">
      <h2 class="brain-card__title"><DashboardOutlined /> 水情与闸门</h2>

      <p class="gate-connection">
        <i :class="{ online: mqttConnected }"></i>
        {{ connectionText }}
        <span v-if="controlNotice" class="control-notice" :class="{ error: controlNotice.error }">
          {{ controlNotice.text }}
        </span>
      </p>

      <div class="brain-metrics">
        <div class="brain-metric">
          <span class="brain-metric__label">当前水位</span>
          <div class="brain-metric__value" :style="{ color: levelColor }">
            {{ waterText }}<span class="brain-metric__unit">m</span>
          </div>
          <div class="brain-metric__hint">{{ levelText }}</div>
        </div>
        <div class="brain-metric">
          <span class="brain-metric__label">开启闸门</span>
          <div class="brain-metric__value">{{ openCount }}<span class="brain-metric__unit">/ {{ SCHEDULE_GATE_COUNT }}</span></div>
          <div class="brain-metric__hint">{{ openCount ? `已开 ${openList}` : '全部关闭' }}</div>
        </div>
        <div class="brain-metric">
          <span class="brain-metric__label">AI 建议档位</span>
          <div class="brain-metric__value">{{ aiLevelText }}</div>
          <div class="brain-metric__hint">{{ aiHint }}</div>
        </div>
        <div class="brain-metric">
          <span class="brain-metric__label">预测误差</span>
          <div class="brain-metric__value">{{ avgErrorText }}</div>
          <div class="brain-metric__hint">已学 {{ brain?.learning?.learnCount ?? 0 }} 轮</div>
        </div>
      </div>

      <!-- 4 路放水闸门：手动开关 -->
      <div class="gate-control-grid">
        <div v-for="(state, index) in gates" :key="index" class="gate-control-item">
          <div>
            <strong>{{ index + 1 }}号闸门</strong>
            <span :class="!hasGateStatus ? 'closed' : state === 1 ? 'open' : 'closed'">
              {{ !hasGateStatus ? '等待数据' : state === 1 ? '开启' : '关闭' }}
            </span>
          </div>
          <button
            type="button"
            class="gate-toggle"
            :class="state === 1 ? 'is-open' : 'is-closed'"
            :disabled="!mqttConnected || !hasGateStatus"
            :aria-label="state === 1 ? `关闭${index + 1}号闸门` : `开启${index + 1}号闸门`"
            @click="requestGate(index + 1)"
          >
            <span class="gate-toggle__track"><span class="gate-toggle__thumb" /></span>
            <span class="gate-toggle__label">
              <b>{{ !hasGateStatus ? '等待状态数据' : state === 1 ? '已开启' : '已关闭' }}</b>
              <small>{{ !hasGateStatus ? '等待 RTU 上报' : state === 1 ? '点击关闭' : '点击开启' }}</small>
            </span>
            <component :is="state === 1 ? ArrowDownOutlined : ArrowUpOutlined" class="gate-toggle__icon" />
          </button>
        </div>
      </div>

      <p class="gate-note">
        1~4 号为放水闸门，开得越多水位下降越快；5~6 号为循环回抽泵，仅采集训练数据时使用，不参与调度。
      </p>
    </section>

    <!-- ══════════ AI 决策 ══════════ -->
    <section class="brain-card">
      <div class="ai-head">
        <h2 class="brain-card__title"><ExperimentOutlined /> AI 闸门决策</h2>
        <span class="badge" :class="aiStatusClass"><i class="dot" />{{ aiStatusLabel }}</span>
      </div>

      <p v-if="!aiOnline" class="hint warn">
        AI 决策服务不可达，闸门仍可手动控制。启动方式：
        <code>python -m uvicorn server:app --port 5001</code>
      </p>

      <template v-if="aiOnline">
        <div v-if="decision" class="reason">
          <span class="reason__label">最近决策</span>
          <p class="reason__text">{{ decision.explanation }}</p>
          <p class="reason__meta">
            建议 {{ decision.action }} 门 / 共 {{ decision.gateCount }}
            · 预测终点 {{ Number(decision.predictedFinal ?? 0).toFixed(3) }} m
            · 代价 {{ Number(decision.bestCost ?? 0).toFixed(1) }}
            <template v-if="decision.forced"> · 应急强制</template>
          </p>
          <p class="reason__meta">本轮闸门变更：{{ gatePlanText }}</p>
        </div>

        <div class="ai-actions">
          <button type="button" class="btn ghost" :disabled="aiPending" @click="refreshAi">刷新</button>
          <button type="button" class="btn ghost" :disabled="aiPending" @click="onResetAi">复位</button>
          <button
            type="button"
            class="btn danger"
            :disabled="aiPending || openCount === 0"
            @click="onCloseAllAi"
          >
            全部关闸
          </button>
        </div>
      </template>
    </section>
  </ViewShell>
</template>

<script setup>
/**
 * 防汛调度：闸门控制台 + AI 决策。
 *
 * 两个控制来源并存（按运维要求不做互斥）：
 * - **手动**：本页开关直接经前端 MQTT 发布 `rtu/control`；
 * - **AI**：Python 推理服务同样发布 `rtu/control`。
 *
 * 两者都发指令时后发者生效。界面不阻止这种竞争，但会把 AI 的当前建议
 * 与闸门真实状态同时显示出来，让运维能看出"是谁在动"，而不是面对一个
 * 突然变化的开关。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  ArrowDownOutlined,
  ArrowUpOutlined,
  DashboardOutlined,
  ExperimentOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { SCHEDULE_GATE_COUNT, useReservoirMqtt } from '../composables/useReservoirMqtt.js'
import {
  controlBrainGates,
  getBrainHealth,
  getBrainStatus,
  resetBrain,
} from '../api/brain'

const { mqttConnected, realtime, gates, toggleGate } = useReservoirMqtt()

const hasGateStatus = computed(() => Boolean(realtime.value?.relayReported))
const controlNotice = ref(null)

// ── 闸门手动控制 ──────────────────────────────────────────────

function requestGate(id) {
  if (!hasGateStatus.value) return
  const ok = toggleGate(id)
  controlNotice.value = ok
    ? { text: `${id}号闸门控制指令已发布`, error: false }
    : { text: 'MQTT 未连接，指令未发布', error: true }
  window.setTimeout(() => { controlNotice.value = null }, 3200)
}

const openCount = computed(() => gates.value.filter((v) => v === 1).length)
const openList = computed(() =>
  gates.value.map((v, i) => (v === 1 ? i + 1 : null)).filter(Boolean).map((i) => `#${i}`).join('、')
)

const waterText = computed(() => {
  const v = realtime.value?.level
  return v === null || v === undefined ? '—' : Number(v).toFixed(3)
})

const levelText = computed(() => {
  const v = realtime.value?.level
  if (v === null || v === undefined) return '等待数据'
  if (v <= 0.20) return '死水位'
  if (v <= 0.30) return '濒死'
  if (v <= 0.80) return '正常'
  if (v <= 1.10) return '预警'
  return '应急'
})

const levelColor = computed(() => {
  const v = realtime.value?.level
  if (v === null || v === undefined) return '#163956'
  if (v <= 0.30) return '#c9392f'
  if (v >= 1.20) return '#c9392f'
  if (v >= 0.80) return '#b47c10'
  return '#1a9f66'
})

const connectionText = computed(() => {
  if (!mqttConnected.value) return 'MQTT 未连接，无法下发控制指令'
  return hasGateStatus.value ? '已收到闸门状态，数据来自 rtu/status' : 'MQTT 已连接，等待 rtu/status 闸门数据'
})

const shellTag = computed(() => (mqttConnected.value ? '闸门控制 · MQTT 已连接' : '闸门控制 · 等待 MQTT'))

// ── AI 决策 ──────────────────────────────────────────────────

const AI_POLL = 2000
const aiStatus = ref(null)
const aiOnline = ref(false)
const aiPending = ref(false)

let aiTimer = null
let disposed = false

const brain = computed(() => aiStatus.value?.brain ?? null)
const pending = computed(() => brain.value?.gate?.pending ?? null)
const aiNeedsConfirm = computed(() => brain.value?.gate?.state === 'pending')
const decision = computed(() => brain.value?.decision ?? null)
const aiLevelText = computed(() => {
  if (!aiOnline.value) return '—'
  const a = decision.value?.action
  return a === undefined || a === null ? '—' : `${a}`
})
const aiHint = computed(() => {
  if (!aiOnline.value) return '服务离线'
  if (aiNeedsConfirm.value) return '等待人工确认'
  return decision.value?.explanation ? '见下方理由' : '预热中'
})
const avgErrorText = computed(() => {
  const v = brain.value?.learning?.averageError
  return v === null || v === undefined ? '—' : Number(v).toFixed(4)
})
const gatePlanText = computed(() => {
  const p = brain.value?.gatePlan
  if (!p) return '—'
  const parts = []
  if (p.open?.length) parts.push(`开 #${p.open.join('、#')}`)
  if (p.close?.length) parts.push(`关 #${p.close.join('、#')}`)
  return parts.length ? parts.join('；') : '无变化'
})
const aiStatusClass = computed(() => {
  if (!aiOnline.value) return 'down'
  if (aiNeedsConfirm.value) return 'alert'
  if ((brain.value?.gates?.currentLevel ?? 0) > 0) return 'active'
  return 'ok'
})
const aiStatusLabel = computed(() => {
  if (!aiOnline.value) return '服务离线'
  if (!brain.value?.ready) return '预热中'
  if (aiNeedsConfirm.value) return '等待确认'
  const lv = brain.value?.gates?.currentLevel ?? 0
  return lv > 0 ? `AI 开闸中 ${lv}/${SCHEDULE_GATE_COUNT}` : '运行中'
})

async function refreshAi() {
  if (disposed) return
  try {
    await getBrainHealth()
    aiStatus.value = await getBrainStatus()
    aiOnline.value = true
  } catch {
    aiOnline.value = false
  } finally {
    scheduleAi()
  }
}

function scheduleAi() {
  if (disposed) return
  clearTimeout(aiTimer)
  aiTimer = setTimeout(refreshAi, aiOnline.value ? AI_POLL : AI_POLL * 3)
}

async function runAi(action) {
  aiPending.value = true
  try {
    await action()
    await refreshAi()
  } catch (err) {
    controlNotice.value = { text: err.message || 'AI 操作失败', error: true }
    window.setTimeout(() => { controlNotice.value = null }, 4000)
  } finally {
    aiPending.value = false
  }
}

const onResetAi = () => runAi(() => resetBrain(false))
const onCloseAllAi = () => runAi(() => controlBrainGates(0))

onMounted(() => {
  refreshAi()
})

onBeforeUnmount(() => {
  disposed = true
  clearTimeout(aiTimer)
})
</script>

<style scoped>
/* ── 卡片容器 ──
   原本想复用 ViewShell.css 的 .view-card，但那些规则定义在父组件作用域，
   scoped 子组件拿不到（除非用 :deep）。这里按同样规格本地定义，
   视觉与平台其它页面一致，又不依赖父组件样式的实现细节。 */
.brain-card{padding:18px;border:1px solid #e2ebf3;border-radius:15px;background:rgba(255,255,255,.93);box-shadow:0 8px 22px rgba(31,80,117,.06);margin-bottom:16px}
.brain-card__title{display:flex;align-items:center;gap:8px;margin:0 0 14px;color:#1b3e5c;font-size:14px;font-weight:650}
.brain-card__title :deep(svg){color:#2385db}

.gate-connection{display:flex;align-items:center;gap:7px;margin:-4px 0 13px;color:#8196a6;font-size:11px}.gate-connection i{width:7px;height:7px;border-radius:50%;background:#c0cbd2}.gate-connection i.online{background:#27c49a}.control-notice{margin-left:auto;color:#1b9e76}.control-notice.error{color:#bd5b45}
.gate-control-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:16px}
.gate-control-item{padding:13px;border:1px solid #e5edf3;border-radius:12px;background:linear-gradient(145deg,#fff 0%,#f8fbfd 100%);box-shadow:0 6px 16px rgba(38,83,116,.045)}
.gate-control-item>div{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px}
.gate-control-item strong{color:#3c5e76;font-size:11px}
.gate-control-item span{font-size:10px}
.gate-control-item span.open{color:#188f6e}
.gate-control-item span.closed{color:#8195a4}
.gate-toggle{display:flex;align-items:center;gap:9px;width:100%;min-height:48px;padding:7px 9px;border:1px solid #e0eaf1;border-radius:12px;outline:none;background:#f7fafc;color:#547189;text-align:left;cursor:pointer;transition:border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .18s ease}
.gate-toggle:focus-visible{border-color:#64b6e8;box-shadow:0 0 0 3px rgba(56,157,218,.18)}
.gate-toggle:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 7px 14px rgba(35,89,122,.1)}
.gate-toggle:active:not(:disabled){transform:scale(.985)}
.gate-toggle:disabled{cursor:not-allowed;opacity:.5;filter:grayscale(.35)}
.gate-toggle__track{position:relative;flex:0 0 40px;width:40px;height:23px;border-radius:99px;background:#d9e5ed;box-shadow:inset 0 1px 3px rgba(21,67,95,.16);transition:background .2s ease}
.gate-toggle__thumb{position:absolute;top:3px;left:3px;width:17px;height:17px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(20,64,88,.22);transition:transform .2s ease}
.gate-toggle.is-open{border-color:#b7ead8;background:linear-gradient(135deg,#f6fffb,#e8faf3)}
.gate-toggle.is-open .gate-toggle__track{background:#2abf92}
.gate-toggle.is-open .gate-toggle__thumb{transform:translateX(17px)}
.gate-toggle.is-closed:hover:not(:disabled){border-color:#bcd8e9;background:#f1f8fc}
.gate-toggle__label{display:flex;flex:1;flex-direction:column;gap:2px;min-width:0}
.gate-toggle__label b{color:#355b73;font-size:10px;font-weight:650}
.gate-toggle.is-open .gate-toggle__label b{color:#168c6c}
.gate-toggle__label small{color:#91a4b2;font-size:9px}
.gate-toggle__icon{flex:0 0 auto;color:#8ca5b4;font-size:12px}
.gate-toggle.is-open .gate-toggle__icon{color:#24a77f}
.gate-note{margin:14px 0 0;color:#8196a6;font-size:10.5px;line-height:1.6}

/* ── AI 区块 ── */
.ai-head{display:flex;align-items:center;justify-content:space-between;gap:12px}
.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 11px;border-radius:9px;font-size:10.5px;white-space:nowrap;background:#f0f5f9;color:#557188;border:1px solid #e2ebf3}
.badge .dot{width:6px;height:6px;border-radius:50%;background:currentColor}
.badge.ok{color:#1a9f66;background:rgba(49,217,161,.1);border-color:rgba(49,217,161,.32)}
.badge.active{color:#1676e8;background:rgba(22,118,232,.09);border-color:rgba(22,118,232,.3)}
.badge.alert{color:#b47c10;background:rgba(233,170,39,.12);border-color:rgba(233,170,39,.36)}
.badge.down{color:#c9392f;background:rgba(230,86,76,.1);border-color:rgba(230,86,76,.3)}
.hint{margin:0 0 14px;padding:10px 12px;border-radius:9px;font-size:11.5px;line-height:1.7;color:#4a6b88;background:rgba(22,118,232,.05);border:1px solid rgba(22,118,232,.16)}
.hint.warn{color:#8a6410;background:rgba(233,170,39,.08);border-color:rgba(233,170,39,.26)}
.hint code{padding:1px 5px;border-radius:4px;background:#eef4f9;color:#2b5578;font-size:10.5px}
.reason{padding:13px 15px;border-radius:11px;background:#fbfdfe;border:1px solid #e5edf4;border-left:3px solid #2385db}
.reason__label{color:#7188a0;font-size:11px}
.reason__text{margin:5px 0 0;color:#2b5578;font-size:12.5px;line-height:1.65}
.reason__meta{margin:5px 0 0;color:#8095a7;font-size:10.5px}
.ai-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:14px}
.btn{padding:7px 15px;border-radius:9px;font-size:11.5px;font-weight:500;cursor:pointer;border:1px solid transparent;transition:background .16s ease,border-color .16s ease,opacity .16s ease}
.btn:disabled{opacity:.42;cursor:not-allowed}
.btn.ghost{color:#4a6b88;background:#f4f8fb;border-color:#e2ebf3}
.btn.ghost:hover:not(:disabled){background:#eaf2f9;border-color:#cfe0ee}
.btn.primary{color:#fff;background:#1676e8;border-color:#1676e8}
.btn.danger{color:#c9392f;background:rgba(230,86,76,.07);border-color:rgba(230,86,76,.3)}

/* ── 确认弹窗 ── */

/* ── 指标卡：横向四列 ──
   不复用 ViewShell.css 的 .view-metrics：那个类的栅格定义在父组件作用域，
   scoped 样式拿不到，会导致卡片塌成一列。这里自定义同规格的栅格。 */
.brain-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px;margin-top:14px}
.brain-metric{padding:15px;border:1px solid #e5edf4;border-radius:11px;background:#fbfdfe}
.brain-metric__label{display:block;color:#7188a0;font-size:11px}
.brain-metric__value{margin-top:5px;color:#163956;font-size:23px;font-weight:700;font-variant-numeric:tabular-nums;line-height:1.2}
.brain-metric__unit{margin-left:4px;color:#7188a0;font-size:11px;font-weight:500}
.brain-metric__hint{margin-top:3px;color:#8095a7;font-size:10px}
</style>
