// AI 回答的 Markdown 渲染：先转 HTML，再消毒，最后把安全警示关键词标红。
//
// 回答来自 Dify / 知识库，属于不可信内容；这里不做任何“信任模型输出”的假设，
// 所有 HTML 都经过 DOMPurify 白名单过滤，链接统一加 noopener。

import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { DANGER_KEYWORDS } from './highlight.js'

const SANITIZE_CONFIG = {
  ALLOWED_TAGS: [
    'p', 'br', 'strong', 'b', 'em', 'i', 'del', 's',
    'code', 'pre', 'blockquote',
    'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'hr', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'span', 'mark',
  ],
  ALLOWED_ATTR: ['href', 'title', 'target', 'rel', 'class', 'start'],
  ALLOW_DATA_ATTR: false,
}

// 链接一律新窗口打开，避免把当前问答页面顶掉
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

/**
 * 把 Markdown 转成可安全插入 DOM 的 HTML。
 *
 * @param {string} text
 * @returns {string}
 */
export function renderMarkdown(text) {
  if (!text) return ''
  const raw = marked.parse(text, { async: false, gfm: true, breaks: true })
  const safe = DOMPurify.sanitize(raw, SANITIZE_CONFIG)
  return highlightDanger(safe)
}

/**
 * 在文本节点里把“严禁 / 危险 / 立即上报”等关键词包成 <mark>。
 *
 * 只处理文本节点，跳过代码、链接和已高亮区域，避免破坏 Markdown 结构或
 * 在代码示例里误标红。
 */
function highlightDanger(html) {
  if (!DANGER_KEYWORDS.length) return html

  const template = document.createElement('template')
  template.innerHTML = html

  const walker = document.createTreeWalker(template.content, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const text = node.nodeValue
      if (!text || !text.trim()) return NodeFilter.FILTER_REJECT
      if (node.parentElement?.closest('pre, code, a, mark')) return NodeFilter.FILTER_REJECT
      return DANGER_KEYWORDS.some((keyword) => text.includes(keyword))
        ? NodeFilter.FILTER_ACCEPT
        : NodeFilter.FILTER_REJECT
    },
  })

  const nodes = []
  while (walker.nextNode()) nodes.push(walker.currentNode)

  for (const node of nodes) {
    const fragment = document.createDocumentFragment()
    let rest = node.nodeValue || ''
    while (rest) {
      const hit = earliestKeyword(rest)
      if (!hit) {
        fragment.appendChild(document.createTextNode(rest))
        break
      }
      if (hit.index > 0) {
        fragment.appendChild(document.createTextNode(rest.slice(0, hit.index)))
      }
      const mark = document.createElement('mark')
      mark.className = 'md-danger'
      mark.textContent = hit.keyword
      fragment.appendChild(mark)
      rest = rest.slice(hit.index + hit.keyword.length)
    }
    node.parentNode?.replaceChild(fragment, node)
  }

  return template.innerHTML
}

/** 找出最先出现的关键词；同位置取更长的，避免“危险”覆盖“危险区域” */
function earliestKeyword(text) {
  let best = null
  for (const keyword of DANGER_KEYWORDS) {
    const index = text.indexOf(keyword)
    if (index < 0) continue
    if (!best || index < best.index || (index === best.index && keyword.length > best.keyword.length)) {
      best = { index, keyword }
    }
  }
  return best
}
