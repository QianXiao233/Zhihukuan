// 解析 Dify 回答中携带的跳转指令

/** 平台支持的页面标识，与路由表一一对应 */
const VALID_TARGETS = ['home', 'monitor', 'inspection', 'policy', 'flood', 'ecology']

/**
 * 中文页面名 → 页面标识，用于宽容匹配模型输出的自然语言
 * @type {Record<string, import('../types.js').NavigateTarget>}
 */
const ALIASES = {
  首页: 'home',
  主页: 'home',
  水库监测: 'monitor',
  监测总览: 'monitor',
  监测: 'monitor',
  巡检: 'inspection',
  巡查: 'inspection',
  巡检台账: 'inspection',
  政策: 'policy',
  法规: 'policy',
  政策文档: 'policy',
  防汛: 'flood',
  调度: 'flood',
  泄洪: 'flood',
  生态: 'ecology',
  放流: 'ecology',
}

/**
 * @param {unknown} raw
 * @returns {import('../types.js').NavigateTarget | null}
 */
function normalizeTarget(raw) {
  if (typeof raw !== 'string') return null
  const key = raw.trim()
  if (!key) return null

  const lower = key.toLowerCase()
  if (VALID_TARGETS.includes(lower)) return /** @type {any} */ (lower)

  // 中文别名
  if (ALIASES[key]) return ALIASES[key]
  // 部分匹配，例如 "监测总览页面"
  for (const [alias, target] of Object.entries(ALIASES)) {
    if (key.includes(alias)) return target
  }
  return null
}

/**
 * 从一段文本里提取跳转指令。支持四种写法（按优先级）：
 *
 *   ① Dify 实际使用的行内标记：  [[jump:monitor]]
 *   ② Markdown 代码块：
 *      ```navigate
 *      {"action":"navigate","target":"monitor","reason":"..."}
 *      ```
 *   ③ 自闭合标签：              <navigate target="monitor" reason="..." />
 *   ④ 无参数标记：              [[jump]]
 *
 * @typedef {Object} ParsedReply
 * @property {string} text 去除指令与思考链后的正文，直接展示给用户
 * @property {import('../types.js').NavigateCommand | null} command 解析出的跳转指令
 */

/** ① [[jump:target]] / [[jump:target|原因]] —— Dify 实际输出的格式 */
const JUMP_MARK_RE = /\[\[\s*jump\s*:\s*([^\]|]+?)\s*(?:\|\s*([^\]]+?)\s*)?\]\]/gi
/** ② ```navigate ... ``` 代码块 */
const CODE_BLOCK_RE = /```(?:navigate|json:nav|nav)\s*([\s\S]*?)```/i
/** ③ <navigate ... /> 自闭合标签 */
const TAG_RE = /<navigate\b([^>]*)\/?>/i
/** ④ 无 target 的裸标记 [[jump]] */
const BARE_JUMP_RE = /\[\[\s*jump\s*\]\]/gi

/** 思维链标签：模型内部推理，必须从展示内容中剔除 */
const THINK_BLOCK_RE = /<think\b[^>]*>[\s\S]*?<\/think>/gi
/** 未闭合的 <think>（流式输出中会出现） */
const OPEN_THINK_RE = /<think\b[^>]*>[\s\S]*$/i

/**
 * @param {string} attrs
 * @param {string} name
 * @returns {string | undefined}
 */
function readAttr(attrs, name) {
  const m = new RegExp(`${name}\\s*=\\s*["']([^"']*)["']`, 'i').exec(attrs)
  return m?.[1]
}

/**
 * 剥离思维链内容。
 *
 * 注意：流式渲染时 <think> 尚未闭合，此时应把已出现的思考内容整段丢弃，
 * 否则用户会看到模型内心独白。
 *
 * @param {string} raw
 * @returns {string}
 */
export function stripThink(raw) {
  if (!raw) return ''
  return raw.replace(THINK_BLOCK_RE, '').replace(OPEN_THINK_RE, '')
}

/**
 * 剔除跳转标记，并缓冲末尾「尚未闭合的标记」。
 *
 * 流式渲染时 `[[jump:monitor]]` 可能只到达 `[[jump:`，
 * 此时应暂不展示，否则用户会看到半截标记。
 *
 * @param {string} raw
 * @returns {string}
 */
export function stripJumpMarks(raw) {
  if (!raw) return ''
  // 带 g 标志的正则有 lastIndex 状态，复用前需重置，否则会漏匹配
  JUMP_MARK_RE.lastIndex = 0
  BARE_JUMP_RE.lastIndex = 0
  let text = raw.replace(JUMP_MARK_RE, '').replace(BARE_JUMP_RE, '')

  const open = text.lastIndexOf('[[')
  if (open >= 0 && text.indexOf(']]', open) < 0) {
    text = text.slice(0, open)
  }
  return text
}

/**
 * 解析 AI 回答：抽出导航指令，返回纯正文 + 指令。
 * 指令可能出现在流式输出的任意位置，因此每次增量都重新解析。
 *
 * @param {string} raw
 * @returns {ParsedReply}
 */
export function parseReply(raw) {
  if (!raw) return { text: '', command: null }

  // 先剥离思维链，避免思考内容被当作正文展示
  let text = stripThink(raw)
  /** @type {import('../types.js').NavigateCommand | null} */
  let command = null

  // ① [[jump:target]] / [[jump:target|原因]]
  JUMP_MARK_RE.lastIndex = 0
  const jumpMatch = JUMP_MARK_RE.exec(text)
  if (jumpMatch) {
    const target = normalizeTarget(jumpMatch[1])
    if (target) {
      command = {
        action: 'navigate',
        target,
        reason: jumpMatch[2]?.trim(),
      }
    }
  }
  // 移除所有 jump 标记（含无法识别的、以及流式中途未闭合的），避免残留在正文里
  text = stripJumpMarks(text)

  // ② JSON 代码块
  if (!command) {
    const blockMatch = CODE_BLOCK_RE.exec(text)
    if (blockMatch) {
      const json = blockMatch[1].trim()
      try {
        const obj = JSON.parse(json)
        const target = normalizeTarget(obj.target ?? obj.page ?? obj.route)
        if (target) {
          command = {
            action: 'navigate',
            target,
            params: obj.params ?? undefined,
            reason: typeof obj.reason === 'string' ? obj.reason : undefined,
          }
        }
      } catch {
        // JSON 不合法则忽略该块
      }
      text = text.replace(blockMatch[0], '')
    }
  }

  // ③ <navigate ... /> 标签
  if (!command) {
    const tagMatch = TAG_RE.exec(text)
    if (tagMatch) {
      const target = normalizeTarget(readAttr(tagMatch[1], 'target'))
      if (target) {
        command = {
          action: 'navigate',
          target,
          reason: readAttr(tagMatch[1], 'reason'),
        }
      }
      text = text.replace(tagMatch[0], '')
    }
  }

  return { text: text.trim(), command }
}
