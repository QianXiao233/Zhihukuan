const authHeaders = () => {
  const token = localStorage.getItem('token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  })
  const body = await response.json().catch(() => null)
  if (!body) throw new Error('服务未返回有效数据，请检查后端是否启动')
  if (!response.ok || body.success === false) {
    throw new Error(body.message || `请求失败（${response.status}）`)
  }
  return body
}

function formBody(values, snakeCase = true) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== null) params.set(snakeCase ? key.replace(/[A-Z]/g, (char) => `_${char.toLowerCase()}`) : key, String(value))
  })
  return params
}

export const listDevices = () => request('/api/manage/device/list')
export const addDevice = (values) => request('/api/manage/device/add', { method: 'POST', body: formBody(values) })
export const updateDevice = (values) => request('/api/manage/device/update', { method: 'POST', body: formBody(values) })
export const deleteDevice = (deviceId) => request('/api/manage/device/delete', { method: 'POST', body: formBody({ deviceId }, false) })

export const listParams = () => request('/api/manage/param/list')
export const addParam = (values) => request('/api/manage/param/add', { method: 'POST', body: formBody(values) })
export const updateParam = (values) => request('/api/manage/param/update', { method: 'POST', body: formBody(values) })
export const deleteParam = (paramId) => request('/api/manage/param/delete', { method: 'POST', body: formBody({ paramId }, false) })

export const listDams = () => request('/api/manage/dam/list')
export const addDam = (values) => request('/api/manage/dam/add', { method: 'POST', body: formBody(values) })
export const updateDam = (values) => request('/api/manage/dam/update', { method: 'POST', body: formBody(values) })
export const deleteDam = (damId) => request('/api/manage/dam/delete', { method: 'POST', body: formBody({ damId }, false) })

export const listUsers = () => request('/api/manage/user/list')
export const addUser = (values) => request('/api/manage/user/add', { method: 'POST', body: formBody(values) })
export const updateUser = (values) => request('/api/manage/user/update', { method: 'POST', body: formBody(values) })
export const deleteUser = (id) => request('/api/manage/user/delete', { method: 'POST', body: formBody({ id }) })
export const changePassword = (oldPassword, newPassword) => request('/api/manage/user/password', { method: 'POST', body: formBody({ oldPassword, newPassword }, false) })

// ─────────── 水情数据（MongoDB） ───────────

/** 旧接口：实时监测页取最近 N 条 + 总数 */
export const dataSummary = (limit = 20, page = 1, start = '', end = '') => request(`/api/manage/data/summary?${new URLSearchParams({ limit, page, start, end })}`)

/** 把页面上的筛选状态转成后端参数（键名与 WaterQuery 对齐） */
export function waterFilterParams(filters = {}, extra = {}) {
  const params = new URLSearchParams()
  const put = (key, value) => {
    if (value !== undefined && value !== null && String(value).trim() !== '') params.set(key, String(value).trim())
  }
  put('start', filters.start)
  put('end', filters.end)
  put('min_level', filters.minLevel)
  put('max_level', filters.maxLevel)
  put('min_temperature', filters.minTemperature)
  put('max_temperature', filters.maxTemperature)
  put('min_ph', filters.minPh)
  put('max_ph', filters.maxPh)
  put('min_orp', filters.minOrp)
  put('max_orp', filters.maxOrp)
  const gates = Array.isArray(filters.gates) ? filters.gates : []
  gates.forEach((value, index) => { if (value !== '' && value !== null && value !== undefined) params.set(`relay${index + 1}`, String(value)) })
  if (filters.abnormal) params.set('abnormal', 'true')
  put('granularity', extra.granularity)
  put('page', extra.page ?? filters.page)
  put('size', extra.size ?? filters.size)
  put('sort', extra.sort ?? filters.sort)
  return params
}

export const queryWaterLogs = (filters = {}, extra = {}) => request(`/api/manage/data/query?${waterFilterParams(filters, extra)}`)
export const waterStats = (filters = {}, granularity = 'hour') => request(`/api/manage/data/stats?${waterFilterParams(filters, { granularity })}`)
export const waterStorage = () => request('/api/manage/data/storage')
export const migrateWaterLogs = () => request('/api/manage/data/migrate', { method: 'POST' })

export async function exportWaterLogs(filters = {}) {
  const response = await fetch(`/api/manage/data/export?${waterFilterParams(filters, { page: 1 })}`, { headers: authHeaders() })
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.message || '导出失败')
  }
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `water-log-${Date.now()}.csv`
  anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export const cleanWaterLogs = (beforeTime) => request('/api/manage/data/clean-before', { method: 'POST', body: formBody({ beforeTime }, false) })

// ─────────── 推送配置 / 实时监控 ───────────

export const getPushConfig = () => request('/api/manage/push/config')
export const savePushConfig = (values) => request('/api/manage/push/config', { method: 'POST', body: formBody(values, false) })
export const testPush = () => request('/api/manage/push/test', { method: 'POST' })
export const resetPushCooldown = () => request('/api/manage/push/cooldown/reset', { method: 'POST' })
export const monitorStatus = () => request('/api/manage/monitor/status')

export const listAudit = (page = 1, query = '') => request(`/api/manage/audit/list?${new URLSearchParams({ page, query })}`)
export const getRuntime = () => request('/api/manage/runtime')

// ─────────── 服务间消息总线（消息存 MongoDB） ───────────

/** 队列计数 + 客户端列表，一次请求拿全 */
export const listBusStatus = () => request('/api/manage/bus/status')
export const createBusClient = (values) => request('/api/manage/bus/clients', { method: 'POST', body: formBody(values) })
export const setBusClientEnabled = (clientId, enabled) => request('/api/manage/bus/clients/enable', { method: 'POST', body: formBody({ clientId, enabled }) })
export const rotateBusClient = (clientId) => request('/api/manage/bus/clients/rotate', { method: 'POST', body: formBody({ clientId }) })
export const deleteBusClient = (clientId) => request('/api/manage/bus/clients/delete', { method: 'POST', body: formBody({ clientId }) })

export async function listMessages() {
  const body = await request('/api/manage/messages/list')
  return body.data || []
}

export async function unreadMessageCount() {
  try { return Number((await request('/api/manage/messages/unread-count')).data?.count) || 0 }
  catch { return 0 }
}

export const addMessage = (values) => request('/api/manage/messages/add', { method: 'POST', body: formBody(values) })
export const markMessageRead = (id) => request('/api/manage/messages/read', { method: 'POST', body: formBody({ id }, false) })
export const markAllMessagesRead = () => request('/api/manage/messages/read-all', { method: 'POST' })
export const deleteMessage = (id) => request('/api/manage/messages/delete', { method: 'POST', body: formBody({ id }, false) })
export const recallMessage = (id) => request('/api/manage/messages/recall', { method: 'POST', body: formBody({ id }, false) })
export const pendingPopups = () => request('/api/manage/messages/pending-popups')
export const markPopupDone = (id) => request('/api/manage/messages/popup-done', { method: 'POST', body: formBody({ id }, false) })
