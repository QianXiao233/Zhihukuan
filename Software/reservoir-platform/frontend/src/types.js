/**
 * 数据模型（JSDoc 类型定义）
 *
 * 本文件没有运行时代码，仅提供类型注解，供编辑器做提示与跳转。
 * 用法：
 *   /** @typedef {import('../types.js').ChatMessage} ChatMessage *\/
 */

/**
 * 消息角色
 * @typedef {'user' | 'assistant'} MessageRole
 */

/**
 * 需要高亮的文本片段，type = danger 表示安全警示红色
 * @typedef {Object} MessageHighlight
 * @property {string} text 需要高亮的文本
 * @property {'danger'} type 高亮类型
 */

/** ─────────── 多模态附件 ─────────── */

/**
 * 附件种类
 * @typedef {'image' | 'document'} AttachmentKind
 */

/**
 * 已随消息发送出去的附件
 * @typedef {Object} ChatAttachment
 * @property {string} id
 * @property {string} name 展示用文件名
 * @property {number} size 字节数
 * @property {string} mimeType
 * @property {AttachmentKind} kind
 * @property {string} [remoteId] Dify 上传后返回的文件 id，用于后续对话引用
 * @property {string} [url] 服务端可访问的 URL（图片用于展示）
 * @property {string} [previewUrl] 本地预览地址（仅本地附件有）
 */

/**
 * 输入框里尚未发送的附件（持有原始 File 以便上传）
 * @typedef {ChatAttachment & { file: File }} PendingAttachment
 */

/**
 * 单条对话消息
 * @typedef {Object} ChatMessage
 * @property {string} id
 * @property {MessageRole} role
 * @property {string} content 纯文本正文
 * @property {MessageHighlight[]} [highlights] 红色高亮片段
 * @property {ChatAttachment[]} [attachments] 多模态附件
 * @property {NavigateTarget} [navigateTo] AI 建议跳转到的页面（只显示入口，不自动跳）
 * @property {string} [navigateReason] AI 给出的跳转理由，展示在入口按钮上
 * @property {string} [time]
 */

/**
 * 「大家都在问」标签
 * @typedef {Object} QuickTag
 * @property {string} id
 * @property {string} text
 */

/**
 * 右侧热门问题
 * @typedef {Object} HotQuestion
 * @property {string} id
 * @property {string} text
 * @property {number} heat
 */

/**
 * 右侧快捷跳转卡片
 * @typedef {Object} QuickLink
 * @property {string} id
 * @property {string} title
 * @property {string} description
 * @property {string} icon
 * @property {NavigateTarget} [route] 点击后跳转的路由名
 */

/**
 * 历史对话记录
 * @typedef {Object} HistoryItem
 * @property {string} id
 * @property {string} title
 * @property {string} time
 * @property {ChatMessage[]} messages
 */

/** ─────────── 页面自动跳转 ─────────── */

/**
 * 平台内的页面标识
 * @typedef {'home' | 'monitor' | 'inspection' | 'policy' | 'flood' | 'ecology'} NavigateTarget
 */

/**
 * Dify 下发的导航指令结构
 * @typedef {Object} NavigateCommand
 * @property {'navigate'} action
 * @property {NavigateTarget} target
 * @property {Record<string, string>} [params] 可选参数，例如带上查询条件
 * @property {string} [reason] 给用户的说明文案
 */

/** ─────────── 用户偏好 ─────────── */

/**
 * 正文字号档位
 * @typedef {'small' | 'normal' | 'large' | 'xlarge'} FontSizeLevel
 */

// 无运行时导出，仅作类型声明文件使用
export {}
