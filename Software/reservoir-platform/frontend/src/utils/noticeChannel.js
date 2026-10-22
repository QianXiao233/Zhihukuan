import { reactive } from 'vue'
import { playNoticeSound } from './noticeSound.js'

/**
 * 平台通知频道。
 *
 * 前端默认订阅后端总线的 `ui.#` 频道：先拿一次性票据，再用 EventSource 建 SSE。
 * - 收到 `popup: true` 的消息 → 进入确认队列，弹出必须点“我知道了”的模态框；
 * - 其他消息 → 右上角轻提示，不打断操作。
 *
 * 断线自动重连：票据是一次性的，每次重连都重新申请。
 */
export const NOTICE_CHANNEL = 'ui.#'

export const noticeState = reactive({
  connected: false,
  current: null,
  queue: [],
  toasts: [],
  unread: 0,
})

let source = null
let running = false
let retryTimer = null
let retryDelay = 2000
let toastSeed = 0
const seen = new Set()

function token() {
  return localStorage.getItem('token')
}

async function issueTicket() {
  const response = await fetch('/api/bus/ticket', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token()}` },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok || !body?.ticket) {
    throw new Error(body?.message || '通知频道票据获取失败')
  }
  return body.ticket
}

async function connect() {
  if (!running) return
  try {
    const ticket = await issueTicket()
    if (!running) return
    const url = `/api/bus/subscribe?ticket=${encodeURIComponent(ticket)}&topic=${encodeURIComponent(NOTICE_CHANNEL)}`
    source = new EventSource(url)
    source.addEventListener('ready', () => {
      noticeState.connected = true
      retryDelay = 2000
    })
    source.addEventListener('bus', (event) => {
      try {
        receive(JSON.parse(event.data))
      } catch {
        // 忽略格式异常的消息，不影响后续接收
      }
    })
    source.onerror = () => {
      noticeState.connected = false
      if (source) {
        source.close()
        source = null
      }
      scheduleReconnect()
    }
  } catch {
    noticeState.connected = false
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (!running || retryTimer) return
  retryTimer = window.setTimeout(() => {
    retryTimer = null
    if (!token()) {
      stopNoticeChannel()
      return
    }
    void connect()
  }, retryDelay)
  retryDelay = Math.min(Math.round(retryDelay * 1.6), 15000)
}

function receive(message) {
  const payload = message.payload || {}
  handleNotice({
    id: payload.messageId || message.msgId,
    title: payload.title || message.type || '平台通知',
    content: payload.content || '',
    level: Number(payload.level) || 1,
    popup: payload.popup === true || payload.popup === 'true',
    sound: payload.sound !== false,
    time: payload.time || message.createdAt,
    messageId: payload.messageId,
    topic: message.topic,
  })
}

/** 去重后入队：同一条通知可能同时来自 SSE 和登录补弹 */
function handleNotice(notice) {
  if (!notice.id || seen.has(notice.id)) return
  seen.add(notice.id)
  if (seen.size > 500) seen.clear()
  noticeState.unread += 1
  window.dispatchEvent(new Event('platform-notice'))
  if (notice.popup) {
    noticeState.queue.push(notice)
    showNext()
  } else {
    pushToast(notice)
  }
}

/** 登录/刷新后补弹：拉取当前用户还没确认过的弹窗通知 */
async function loadPendingPopups() {
  const token = localStorage.getItem('token')
  if (!token) return
  try {
    const response = await fetch('/api/manage/messages/pending-popups', {
      headers: { Authorization: `Bearer ${token}` },
    })
    const body = await response.json().catch(() => null)
    for (const item of body?.data || []) {
      handleNotice({
        id: item.id,
        messageId: item.id,
        title: item.type || '平台通知',
        content: item.content || '',
        level: Number(item.level) || 1,
        popup: true,
        sound: item.sound !== false && item.sound !== 0,
        time: item.createTime,
        topic: 'ui.notice',
      })
    }
  } catch {
    // 补弹失败不影响 SSE 实时通知
  }
}

function showNext() {
  if (noticeState.current || !noticeState.queue.length) return
  noticeState.current = noticeState.queue.shift()
  if (noticeState.current.sound) playNoticeSound(noticeState.current.level)
}

/** 用户点“我知道了”后调用；先按当前用户记录确认，再展示下一条 */
export function confirmNotice() {
  const current = noticeState.current
  if (current?.messageId) {
    const token = localStorage.getItem('token')
    if (token) {
      fetch('/api/manage/messages/popup-done', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/x-www-form-urlencoded',
        },
        body: new URLSearchParams({ id: current.messageId }),
      }).catch(() => {})
    }
  }
  noticeState.current = null
  window.setTimeout(showNext, 120)
}

function pushToast(notice) {
  const toastId = ++toastSeed
  noticeState.toasts.push({ ...notice, toastId })
  if (notice.sound) playNoticeSound(notice.level)
  window.setTimeout(() => {
    noticeState.toasts = noticeState.toasts.filter((item) => item.toastId !== toastId)
  }, 6000)
}

export function startNoticeChannel() {
  if (running || !token()) return
  running = true
  void connect()
  void loadPendingPopups()
}

export function stopNoticeChannel() {
  running = false
  noticeState.connected = false
  noticeState.current = null
  noticeState.queue = []
  noticeState.toasts = []
  seen.clear()
  if (source) {
    source.close()
    source = null
  }
  if (retryTimer) {
    window.clearTimeout(retryTimer)
    retryTimer = null
  }
}

if (typeof window !== 'undefined') {
  window.addEventListener('platform-logout', () => stopNoticeChannel())
}
