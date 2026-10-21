// 与 Java 后端（Spring Boot 3）的接口层

/**
 * 流式事件（后端把 Dify 的 SSE 归一化成下面几种 type，前端按 type 分发）
 *
 * @typedef {(
 *   { type: 'text', content: string } |
 *   { type: 'navigate', command: import('../types.js').NavigateCommand } |
 *   { type: 'done', conversation_id: string } |
 *   { type: 'error', message: string }
 * )} StreamEvent
 */

/**
 * 统一响应包装
 * @template T
 * @typedef {Object} ApiResponse
 * @property {number} code
 * @property {string} message
 * @property {T} [data]
 */

/**
 * 健康检查返回
 * @typedef {Object} HealthData
 * @property {string} status
 * @property {string} [dify_api_base]
 * @property {boolean} [dify_key_configured]
 * @property {boolean} [asr_available]
 * @property {string} [tts_provider]
 */

/**
 * 已上传文件的返回结构
 * @typedef {Object} UploadedFileData
 * @property {string} id
 * @property {string} name
 * @property {number} size
 * @property {string} mime_type
 * @property {string} [dify_file_id]
 * @property {string} [url]
 */

/** 后端基地址；开发期由 vite 代理 /api 到 127.0.0.1:8085，故默认空串 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/**
 * 把上传结果补全成消息附件
 *
 * @param {UploadedFileData} uploaded 后端返回的上传结果
 * @param {import('../types.js').ChatAttachment} local 本地附件信息
 * @returns {import('../types.js').ChatAttachment}
 */
export function toChatAttachment(uploaded, local) {
  return {
    ...local,
    remoteId: uploaded.dify_file_id ?? uploaded.id,
    url: uploaded.url ?? local.previewUrl,
  }
}

/** ─────────── ① 流式对话 ─────────── */

/**
 * POST /api/chat/stream
 * 事件格式：data: {"type":"text"|"navigate"|"done"|"error", ...}
 *
 * @param {Object} options
 * @param {string} options.query 用户问题
 * @param {string} options.conversationId 会话 id（首轮为空串）
 * @param {string[]} [options.fileIds] 已上传文件的 Dify file id 列表
 * @param {(evt: StreamEvent) => void} options.onEvent 事件回调
 * @param {AbortSignal} [options.signal] 中止信号
 * @returns {Promise<void>}
 */
export async function streamChat(options) {
  const { query, conversationId, fileIds, onEvent, signal } = options

  const resp = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      conversation_id: conversationId,
      file_ids: fileIds ?? [],
    }),
    signal,
  })

  if (!resp.ok) {
    throw new Error(`对话服务返回 HTTP ${resp.status}`)
  }
  if (!resp.body) {
    throw new Error('对话服务未返回流式响应体')
  }

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    // SSE 以空行分隔事件
    const blocks = buffer.split('\n\n')
    buffer = blocks.pop() ?? ''

    for (const block of blocks) {
      for (const rawLine of block.split('\n')) {
        const line = rawLine.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload || payload === '[DONE]') continue
        try {
          onEvent(JSON.parse(payload))
        } catch {
          // 忽略心跳或非 JSON 行
        }
      }
    }
  }
}

/** ─────────── ② 多模态文件上传 ─────────── */

/**
 * POST /api/files/upload（multipart/form-data，字段名 file）
 * 后端转投 Dify 的文件上传接口，并把 Dify 的 file id 透传回来。
 *
 * @param {File} file
 * @param {AbortSignal} [signal]
 * @returns {Promise<UploadedFileData>}
 */
export async function uploadFile(file, signal) {
  const form = new FormData()
  form.append('file', file, file.name)

  const resp = await fetch(`${API_BASE}/api/files/upload`, {
    method: 'POST',
    body: form,
    signal,
  })
  if (!resp.ok) throw new Error(`文件上传失败：HTTP ${resp.status}`)

  /** @type {ApiResponse<UploadedFileData>} */
  const body = await resp.json()
  if (body.code !== 0 || !body.data) {
    throw new Error(body.message || '文件上传失败')
  }
  return body.data
}

/** ─────────── ③ 语音识别 ─────────── */

/**
 * POST /api/asr（multipart/form-data，字段名 file）
 *
 * @param {Blob} blob WAV 音频
 * @param {AbortSignal} [signal]
 * @returns {Promise<string>}
 */
export async function recognizeSpeech(blob, signal) {
  const form = new FormData()
  form.append('file', blob, 'recording.wav')

  const resp = await fetch(`${API_BASE}/api/asr`, { method: 'POST', body: form, signal })
  if (!resp.ok) throw new Error(`语音识别服务返回 HTTP ${resp.status}`)

  /** @type {{ text?: string }} */
  const data = await resp.json()
  return data.text ?? ''
}

/** ─────────── ④ 健康检查 ─────────── */

/**
 * @param {AbortSignal} [signal]
 * @returns {Promise<HealthData>}
 */
export async function checkHealth(signal) {
  const resp = await fetch(`${API_BASE}/health`, { signal })
  if (!resp.ok) throw new Error(`健康检查返回 HTTP ${resp.status}`)
  return resp.json()
}
