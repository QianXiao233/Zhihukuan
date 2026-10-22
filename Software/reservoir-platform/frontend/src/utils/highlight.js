// 从 AI 回答正文中抽取需要红色高亮的安全警示语句

/** 命中即视为安全警示的关键词 */
export const DANGER_KEYWORDS = [
  '严禁',
  '禁止',
  '不得',
  '立即上报',
  '立即撤离',
  '立即转移',
  '必须立即',
  '危险',
  '务必',
]

/**
 * 按句切分正文，命中安全警示关键词的整句标记为 danger。
 * 用于把后端返回的纯文本回答渲染出红色警示片段。
 *
 * @param {string} content 回答正文
 * @returns {import('../types.js').MessageHighlight[]}
 */
export function extractHighlights(content) {
  if (!content) return []
  const sentences = content
    .split(/(?<=[。；;！!？?])/)
    .map((s) => s.trim())
    .filter(Boolean)

  /** @type {import('../types.js').MessageHighlight[]} */
  const result = []
  for (const sentence of sentences) {
    if (DANGER_KEYWORDS.some((kw) => sentence.includes(kw))) {
      result.push({ text: sentence, type: 'danger' })
    }
  }
  return result
}

/**
 * 当前时间 HH:mm，用于消息时间戳
 * @returns {string}
 */
export function nowTime() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/**
 * 生成本地唯一 id
 * @param {string} [prefix]
 * @returns {string}
 */
export function uid(prefix = 'id') {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`
}
