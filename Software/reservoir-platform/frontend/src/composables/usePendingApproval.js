/**
 * 全局待确认请求的共享状态。
 *
 * 为什么用模块级单例而不是 provide/inject：
 * 确认弹窗挂在 App 根节点，而待确认事件来自 SSE 长连接，两者生命周期
 * 与页面路由无关。单例让"任何一个组件都能触发弹窗、任何页面都在监听"
 * 成为默认行为，不需要在每层组件里逐级透传。
 */
import { computed, reactive } from 'vue'

const state = reactive({
  /** 当前待确认请求；null 表示没有 */
  request: null,
  /** 运维选择的档位（可低于 AI 建议）；null 表示按 AI 建议 */
  overrideLevel: null,
  /** 提交中，防止重复点击 */
  submitting: false,
  /** 最近一次操作结果提示 */
  notice: null,
})

let noticeTimer = null

function setNotice(text, isError = false) {
  state.notice = { text, error: isError }
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { state.notice = null }, 5000)
}

/**
 * 收到一条待确认事件。
 *
 * 幂等：同一次请求可能因为总线的 at-least-once 语义重复投递，
 * 用 `requestId` 去重，避免弹窗反复刷新打断运维的档位选择。
 */
function receive(request) {
  if (!request || !request.requestId) return
  if (state.request?.requestId === request.requestId) return
  state.request = request
  state.overrideLevel = null
}

/** 仅当该请求仍是当前展示的那条时才清除（避免清掉更新的一条） */
function clear(requestId) {
  if (requestId && state.request?.requestId !== requestId) return
  state.request = null
  state.overrideLevel = null
}

export function usePendingApproval() {
  return {
    request: computed(() => state.request),
    overrideLevel: computed({
      get: () => state.overrideLevel,
      set: (v) => { state.overrideLevel = v },
    }),
    submitting: computed(() => state.submitting),
    notice: computed(() => state.notice),
    receive,
    clear,
    setNotice,
    setSubmitting: (v) => { state.submitting = v },
  }
}
