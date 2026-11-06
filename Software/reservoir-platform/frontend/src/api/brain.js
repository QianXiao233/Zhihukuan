/**
 * AI 决策服务接口。
 *
 * 分层（重要）：
 * - **实时状态**（水位、闸门、最近决策）→ 直连 Python 网关。高频快照走消息队列
 *   只会引入延迟与堆积，没有收益。
 * - **待确认开闸请求** → 走后端服务接入总线（`ui.#` 频道 SSE）。这类是「需要人处理
 *   的任务」，要落库、要有投递保证、要能审计，所以不能走实时轮询。
 * - **确认/拒绝** → 先经总线投递回 Python（留痕），再直连 Python 确认接口
 *   （动作要低延迟，且不能被消息重投触发二次开闸）。
 *
 * 服务地址由 VITE_BRAIN_BASE_URL 配置；同域部署时留空由 Nginx 反代。
 */

const BASE_URL = (import.meta.env.VITE_BRAIN_BASE_URL ?? 'http://127.0.0.1:5001').replace(/\/+$/, '')

/** 与服务端 `API_TOKEN` 对应的共享密钥。留空表示服务未开启鉴权 */
const TOKEN = import.meta.env.VITE_BRAIN_TOKEN ?? ''

const authHeaders = () => (TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {})

async function request(path, options = {}) {
  const response = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    const message = body?.detail || body?.message || `请求失败（${response.status}）`
    throw new Error(message)
  }
  if (!body) throw new Error('服务未返回有效数据')
  return body
}

const jsonPost = (path, payload) => request(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(payload ?? {}),
})

/** 健康检查（不鉴权，用于判断服务是否在线） */
export const getBrainHealth = () => request('/health')

/** 完整状态：模型、学习统计、闸门阵列、候选序列 */
export const getBrainStatus = () => request('/api/brain/status')

/**
 * 确认开闸。
 * @param {number|undefined} level 可选：运维指定开启的闸门数，省略则按 AI 建议
 * @param {string|undefined} requestId 待确认请求 id，用于把动作与总线事件对上
 */
export const confirmBrainOpen = (level, requestId) =>
  jsonPost('/api/brain/confirm', { ...(level ? { level } : {}), ...(requestId ? { requestId } : {}) })

/** 拒绝开闸，进入冷却期 */
export const rejectBrainOpen = (reason = '', requestId) =>
  jsonPost('/api/brain/reject', { reason, ...(requestId ? { requestId } : {}) })

/** 复位决策状态。clearCooldowns 默认 false，避免绕过设备保护 */
export const resetBrain = (clearCooldowns = false) => jsonPost('/api/brain/reset', { clearCooldowns })

/** 人工直接控制闸门，绕过 AI。state: 0=全关，N=开 N 个门 */
export const controlBrainGates = (state) => jsonPost('/api/brain/control', { state })

// ══════════════════════════════════════════════════════════════
// 服务接入总线：把"人已处理"这个事实投递回 Python
// ══════════════════════════════════════════════════════════════

/** 与 Python 侧约定的主题 */
export const BRAIN_APPROVAL_TOPIC = 'brain.approval'
/** Python 发布的待确认请求主题 */
export const BRAIN_PENDING_TOPIC = 'brain.pending'

/**
 * 通过后端总线发布一条"已处理"消息。
 *
 * 这**不是**开闸动作本身，只是让 Python 侧知道有人处理过了（审计与状态同步）。
 * 真正的动作由 confirmBrainOpen / rejectBrainOpen 直接调用，避免总线重投
 * 导致同一请求被重复执行。
 *
 * 总线要求服务端 client 凭据（`clientId.secret`），而浏览器用户没有；
 * 因此这里走后端的 `/api/bus/publish` 会失败，改由 Python 侧消费。
 * 前端只负责在 SSE 收到事件后展示与调用确认接口。
 */
export async function publishApprovalAck(payload) {
  // 浏览器身份无法直接发布到总线（需要服务密钥），
  // 这一步交给 Python 在 confirm/reject 返回后自行发布。
  // 这里保留函数以便将来后端提供"用户代理发布"端点时接入。
  return Promise.resolve({ skipped: true, payload })
}
