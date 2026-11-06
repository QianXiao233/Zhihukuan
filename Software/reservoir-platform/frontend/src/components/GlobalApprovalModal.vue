<script setup>
/**
 * 全局开闸确认弹窗。
 *
 * 挂载在 App 根节点，**任意页面**收到待确认请求都会弹出——开闸是物理动作，
 * 不能让运维因为"正好没停在防汛页"而错过。这类请求经服务接入总线
 * （`ui.#` 频道的 `brain.approval_request`）投递，不走实时轮询。
 *
 * 交互要点：
 * - 允许把档位**调低**（AI 建议 4 门，现场判断 1 门够用），强制全盘接受
 *   会让人干脆点拒绝，反而更不安全；
 * - 拒绝/确认都带 `requestId`，防止总线重投导致重复动作；
 * - 提交中禁用按钮，避免连点发出两条开闸。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { confirmBrainOpen, rejectBrainOpen } from '../api/brain'
import { usePendingApproval } from '../composables/usePendingApproval'

const { request, overrideLevel, submitting, notice, receive, clear, setNotice, setSubmitting } =
  usePendingApproval()

const now = ref(Date.now())
let clock = null

/** 来自服务接入总线的待确认事件 */
function onApprovalEvent(event) {
  receive(event.detail)
}

const ageSeconds = computed(() => {
  const created = request.value?.createdAt
  if (!created) return 0
  // 服务端时间可能是 ISO 串或毫秒
  const ts = typeof created === 'number' ? created : Date.parse(created)
  if (!Number.isFinite(ts)) return 0
  return Math.max(0, Math.floor((now.value - ts) / 1000))
})

const suggested = computed(() => Number(request.value?.requestedLevel ?? 1))
const selectedLevel = computed(() => overrideLevel.value ?? suggested.value)
const maxLevel = computed(() => Math.max(suggested.value, 1))

function choose(n) {
  overrideLevel.value = n
}

async function onConfirm() {
  if (!request.value || submitting.value) return
  setSubmitting(true)
  const id = request.value.requestId
  try {
    const body = await confirmBrainOpen(selectedLevel.value, id)
    // 服务端可能因为冷却/超时拒绝；如实告知，不要假装成功
    if (body?.accepted === false) {
      setNotice(body.reason || body.message || '确认未生效', true)
    } else {
      setNotice(body?.message || '已确认开闸')
    }
    clear(id)
  } catch (err) {
    setNotice(err.message || '确认失败', true)
  } finally {
    setSubmitting(false)
  }
}

async function onReject() {
  if (!request.value || submitting.value) return
  setSubmitting(true)
  const id = request.value.requestId
  try {
    const body = await rejectBrainOpen('运维在全局确认弹窗拒绝', id)
    if (body?.accepted === false) {
      setNotice(body.reason || body.message || '拒绝未生效', true)
    } else {
      setNotice(body?.message || '已拒绝')
    }
    clear(id)
  } catch (err) {
    setNotice(err.message || '拒绝失败', true)
  } finally {
    setSubmitting(false)
  }
}

onMounted(() => {
  clock = window.setInterval(() => { now.value = Date.now() }, 1000)
  // 服务接入总线在 noticeChannel 里把 brain.approval_request 转成 window 事件
  window.addEventListener('brain-approval-request', onApprovalEvent)
})
onBeforeUnmount(() => {
  if (clock) window.clearInterval(clock)
  window.removeEventListener('brain-approval-request', onApprovalEvent)
})
</script>

<template>
  <div v-if="request" class="approval-mask" role="dialog" aria-modal="true" aria-labelledby="approval-title">
    <div class="approval-box">
      <div class="approval-head">
        <h3 id="approval-title">AI 建议开闸，请确认</h3>
        <span class="approval-station">{{ request.stationName || '水库监测站' }}</span>
      </div>

      <dl class="approval-facts">
        <div>
          <dt>当前水位</dt>
          <dd>{{ Number(request.water ?? 0).toFixed(3) }}<small>m</small></dd>
        </div>
        <div>
          <dt>水位等级</dt>
          <dd>{{ request.level || '—' }}</dd>
        </div>
        <div>
          <dt>AI 建议</dt>
          <dd>开 {{ suggested }} 门</dd>
        </div>
        <div>
          <dt>预测终点</dt>
          <dd>{{ Number(request.predictedFinal ?? 0).toFixed(3) }}<small>m</small></dd>
        </div>
      </dl>

      <p class="approval-explain">{{ request.explanation }}</p>

      <div class="approval-picker">
        <span class="picker-label">执行档位（可调低）</span>
        <div class="picker-options">
          <button
            v-for="n in maxLevel"
            :key="n"
            type="button"
            class="picker-btn"
            :class="{ selected: selectedLevel === n }"
            :disabled="submitting"
            @click="choose(n)"
          >
            {{ n }} 门
          </button>
        </div>
      </div>

      <p class="approval-notice">开闸会实际动作闸门。拒绝后进入冷却期，期间不再建议开闸。</p>

      <div class="approval-actions">
        <button type="button" class="btn ghost" :disabled="submitting" @click="onReject">拒绝</button>
        <button type="button" class="btn primary" :disabled="submitting" @click="onConfirm">
          {{ submitting ? '提交中…' : `确认开 ${selectedLevel} 门` }}
        </button>
      </div>

      <p class="approval-age">
        该请求已等待 {{ ageSeconds }} 秒，超时未处理会自动失效
      </p>
    </div>
  </div>

  <!-- 操作结果提示：确认/拒绝后短暂显示，不打断其它页面操作 -->
  <div v-if="notice" class="approval-toast" :class="{ error: notice.error }">
    {{ notice.text }}
  </div>
</template>

<style scoped>
.approval-mask {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: rgba(7, 28, 52, .42);
  backdrop-filter: blur(3px);
}

.approval-box {
  width: min(480px, 100%);
  padding: 22px 24px;
  border-radius: 15px;
  background: #fff;
  border: 1px solid #e2ebf3;
  box-shadow: 0 22px 52px rgba(12, 44, 76, .26);
}

.approval-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 15px;
}

.approval-head h3 {
  margin: 0;
  color: #b47c10;
  font-size: 15px;
  font-weight: 650;
}

.approval-station {
  color: #8095a7;
  font-size: 11px;
}

.approval-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(102px, 1fr));
  gap: 9px;
  margin: 0 0 13px;
}

.approval-facts div {
  padding: 9px 11px;
  border-radius: 9px;
  background: #f6f9fb;
  border: 1px solid #edf2f5;
}

.approval-facts dt { color: #7188a0; font-size: 10px; }
.approval-facts dd {
  margin: 3px 0 0;
  color: #163956;
  font-size: 14px;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.approval-facts dd small { margin-left: 3px; font-size: 10px; font-weight: 500; color: #8095a7; }

.approval-explain {
  margin: 0 0 13px;
  color: #2b5578;
  font-size: 12px;
  line-height: 1.7;
}

.approval-picker { margin: 0 0 13px; }
.picker-label { display: block; margin-bottom: 6px; color: #8095a7; font-size: 10.5px; }
.picker-options { display: flex; gap: 6px; flex-wrap: wrap; }

.picker-btn {
  padding: 5px 14px;
  border-radius: 8px;
  font-size: 11.5px;
  cursor: pointer;
  color: #4a6b88;
  background: #f4f8fb;
  border: 1px solid #e2ebf3;
  transition: all .16s ease;
}
.picker-btn:hover:not(:disabled) { background: #eaf2f9; }
.picker-btn:disabled { cursor: not-allowed; opacity: .55; }
.picker-btn.selected { color: #fff; background: #1676e8; border-color: #1676e8; font-weight: 600; }

.approval-notice { margin: 0 0 16px; color: #b47c10; font-size: 10.5px; line-height: 1.6; }

.approval-actions { display: flex; gap: 9px; justify-content: flex-end; }

.btn {
  padding: 7px 16px;
  border-radius: 9px;
  font-size: 11.5px;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background .16s ease, opacity .16s ease;
}
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn.ghost { color: #4a6b88; background: #f4f8fb; border-color: #e2ebf3; }
.btn.ghost:hover:not(:disabled) { background: #eaf2f9; }
.btn.primary { color: #fff; background: #1676e8; border-color: #1676e8; }
.btn.primary:hover:not(:disabled) { background: #1264c9; }

.approval-age {
  margin: 13px 0 0;
  color: #8095a7;
  font-size: 10px;
  text-align: right;
}

.approval-toast {
  position: fixed;
  top: 78px;
  right: 24px;
  z-index: 2100;
  max-width: 320px;
  padding: 10px 14px;
  border-radius: 9px;
  font-size: 12px;
  color: #1a9f66;
  background: #f2fbf7;
  border: 1px solid #c8ecdc;
  box-shadow: 0 10px 26px rgba(20, 80, 60, .12);
}
.approval-toast.error { color: #c9392f; background: #fdf3f2; border-color: #f3cfcc; }
</style>
