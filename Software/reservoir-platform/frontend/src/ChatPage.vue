<template>
  <div class="chat-page">
    <OceanBackground />

    <div class="chat-page__layout">
      <!-- 左侧：3D 数字人 + 页面导航 -->
      <aside class="chat-page__aside chat-page__aside--left">
        <DigitalHuman ref="humanRef" :speaking="speaking" :thinking="thinking" />
        <PageNav class="chat-page__nav" :current="currentRoute" @navigate="handleNavigate" />
      </aside>

      <!-- 中间：标题 / 消息区 / 大家都在问 / 输入区 -->
      <main class="chat-page__main glass-panel">
        <header class="chat-page__header">
          <div class="chat-page__title-row">
            <h1 class="chat-page__title">{{ PROJECT_NAME }}</h1>
            <span class="chat-page__badge" :class="{ 'is-offline': backendOnline === false }">
              <i class="chat-page__badge-dot"></i>
              {{ statusText }}
            </span>
          </div>
          <p class="chat-page__welcome">{{ WELCOME_TEXT }}</p>
        </header>

        <MessageList :messages="messages" :loading="loading" :loading-text="LOADING_TEXT" />

        <QuickTags :tags="QUICK_TAGS" :on-tag-click="handleTagClick" />

        <ChatInput
          :value="input"
          :attachments="pendingAttachments"
          :busy="sending"
          :on-change="handleInputChange"
          :on-attach="handleAttach"
          :on-remove-attachment="handleRemoveAttachment"
          :on-send="handleSend"
        />
      </main>

      <!-- 右侧：热门问题 / 历史对话 / 快捷跳转 / 字号 / 语音播报 -->
      <aside class="chat-page__aside chat-page__aside--right">
        <HotQuestions :questions="HOT_QUESTIONS" :on-question-click="handleQuestionClick" />
        <HistoryPanel :history="history" :on-clear="handleClearHistory" />
        <QuickLinks :links="QUICK_LINKS" :on-link-click="handleLinkClick" />
        <FontSizePanel />
        <VoiceToggle
          :enabled="voiceEnabled"
          :supported="ttsSupported"
          :voice-name="ttsVoiceName"
          :rate="voiceRate"
          :on-rate-change="setVoiceRate"
          :on-toggle="setVoiceEnabled"
        />
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { message as antMessage } from 'ant-design-vue'

import OceanBackground from './components/OceanBackground.vue'
import DigitalHuman from './avatar/DigitalHuman.vue'
import PageNav from './components/PageNav.vue'
import MessageList from './components/MessageList.vue'
import QuickTags from './components/QuickTags.vue'
import ChatInput from './components/ChatInput.vue'
import HotQuestions from './components/HotQuestions.vue'
import HistoryPanel from './components/HistoryPanel.vue'
import QuickLinks from './components/QuickLinks.vue'
import FontSizePanel from './components/FontSizePanel.vue'
import VoiceToggle from './components/VoiceToggle.vue'

import { checkHealth, streamChat, uploadFile, toChatAttachment } from './api/chat.js'
import { parseReply } from './router/navigate.js'
import { useSpeechSynthesis } from './voice/useSpeechSynthesis.js'
import { voiceEnabled, voiceRate, setVoiceEnabled, setVoiceRate } from './composables/usePreferences.js'
import { extractHighlights, nowTime, uid } from './utils/highlight.js'
import {
  HOT_QUESTIONS,
  LOADING_TEXT,
  PROJECT_NAME,
  QUICK_LINKS,
  QUICK_TAGS,
  SAMPLE_MESSAGES,
  WELCOME_TEXT,
} from './mockData.js'

/** 历史记录持久化 key */
const HISTORY_KEY = 'reservoir_chat_history'
/** 历史记录最多保留条数 */
const HISTORY_LIMIT = 20

const route = useRoute()
const router = useRouter()
/** @type {import('vue').Ref<InstanceType<typeof DigitalHuman> | null>} */
const humanRef = ref(null)

// ── 页面状态（全部集中在 ChatPage，子组件受控） ──
const messages = ref(SAMPLE_MESSAGES.map((m) => ({ ...m })))
const input = ref('')
const loading = ref(false)
const sending = ref(false)
/** AI 正在输出回答（驱动嘴型） */
const answering = ref(false)
/** 等待首个字符返回（驱动思考动作） */
const thinking = ref(false)
const history = ref([])
const conversationId = ref('')
const backendOnline = ref(null)
const pendingAttachments = ref([])

/** 当前这轮对话对应的历史条目 id */
let currentHistoryId = ''

// ── 语音合成 ──
const {
  supported: ttsSupported,
  speaking: ttsSpeaking,
  voiceName: ttsVoiceName,
  speak: ttsSpeak,
  cancel: ttsCancel,
} = useSpeechSynthesis({
  // 朗读开始时挥手示意一次，形成拟人化的开场
  onStart: () => humanRef.value?.wave(),
})

/** 数字人口型：AI 输出中或正在朗读时为 true */
const speaking = computed(() => answering.value || ttsSpeaking.value)

const statusText = computed(() => {
  if (backendOnline.value === false) return '后端服务未连接'
  return '水利知识库已就绪'
})

/** 当前路由名，用于高亮导航 */
const currentRoute = computed(() => (route.name) ?? 'home')

// ── 页面跳转 ──

/** 统一的跳转入口：路由 + 数字人反馈 + 提示 */
function navigateTo(target, reason) {
  if (target === currentRoute.value) return
  humanRef.value?.nod()
  void router.push({ name: target })
  antMessage.success(reason || '已为您跳转页面')
}

function handleNavigate(target) {
  navigateTo(target)
}

function handleLinkClick(link) {
  if (link.route) {
    navigateTo(link.route, `正在打开「${link.title}」`)
    return
  }
  antMessage.info(`「${link.title}」功能开发中`)
}

// ── 历史记录 ──

function loadHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_KEY)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) history.value = parsed
  } catch {
    history.value = []
  }
}

function persistHistory() {
  try {
    localStorage.setItem(HISTORY_KEY, JSON.stringify(history.value))
  } catch {
    // 存储配额不足时静默忽略
  }
}

/** 把当前消息写入历史（同一轮会话复用同一条记录） */
function commitHistory() {
  const firstUser = messages.value.find((m) => m.role === 'user')
  if (!firstUser) return

  const title = firstUser.content.trim().slice(0, 18) || '新的对话'
  // 落盘时剥离本地预览 URL，避免存入失效的 blob 地址
  const snapshot = messages.value.map((m) => ({
    ...m,
    attachments: m.attachments?.map(({ previewUrl: _drop, ...rest }) => rest),
  }))

  if (currentHistoryId) {
    const item = history.value.find((h) => h.id === currentHistoryId)
    if (item) {
      item.title = title
      item.time = nowTime()
      item.messages = snapshot
      persistHistory()
      return
    }
  }

  currentHistoryId = uid('hist')
  history.value = [
    { id: currentHistoryId, title, time: nowTime(), messages: snapshot },
    ...history.value,
  ].slice(0, HISTORY_LIMIT)
  persistHistory()
}

function handleClearHistory() {
  history.value = []
  currentHistoryId = ''
  try {
    localStorage.removeItem(HISTORY_KEY)
  } catch {
    // 忽略
  }
}

// ── 消息操作 ──

function appendMessage(message) {
  messages.value = [...messages.value, message]
}

/**
 * 替换整条消息对象以触发列表更新
 * @param {string} id
 * @param {Partial<Pick<import('./types.js').ChatMessage, 'content' | 'highlights' | 'navigateTo'>>} patch
 */
function updateMessage(id, patch) {
  messages.value = messages.value.map((m) => (m.id === id ? { ...m, ...patch } : m))
}

function handleInputChange(value) {
  input.value = value
}

/** 「大家都在问」标签 / 热门问题：点击填充输入框（可编辑后再发） */
function handleTagClick(tag) {
  input.value = tag.text
}

function handleQuestionClick(question) {
  input.value = question.text
}

// ── 附件 ──

function handleAttach(files) {
  pendingAttachments.value = [...pendingAttachments.value, ...files]
}

function handleRemoveAttachment(id) {
  pendingAttachments.value = pendingAttachments.value.filter((a) => a.id !== id)
}

/** 清理所有附件的本地预览地址 */
function clearAttachments() {
  for (const a of pendingAttachments.value) {
    if (a.previewUrl) URL.revokeObjectURL(a.previewUrl)
  }
  pendingAttachments.value = []
}

// ── 发送与流式接收 ──

async function handleSend() {
  const query = input.value.trim()
  const attachments = pendingAttachments.value
  if ((!query && attachments.length === 0) || sending.value) return

  if (query.length > 1000) {
    antMessage.warning('问题长度请控制在 1000 字以内')
    return
  }

  ttsCancel()
  sending.value = true
  loading.value = true
  thinking.value = true

  try {
    // ① 先把附件逐个上传，拿到 Dify 的 file id
    const uploadedIds = []
    const sentAttachments = []

    for (const item of attachments) {
      const uploaded = await uploadFile(item.file)
      const merged = toChatAttachment(uploaded, item)
      sentAttachments.push(merged)
      if (merged.remoteId) uploadedIds.push(merged.remoteId)
    }

    // ② 落用户消息
    appendMessage({
      id: uid('msg'),
      role: 'user',
      content: query,
      attachments: sentAttachments.length > 0 ? sentAttachments : undefined,
      time: nowTime(),
    })
    input.value = ''
    pendingAttachments.value = []

    const replyId = uid('msg')
    appendMessage({ id: replyId, role: 'assistant', content: '', time: nowTime() })

    let raw = ''
    let streamError = ''
    let firstChunk = true
    let navCommand = null

    try {
      await streamChat({
        query,
        conversationId: conversationId.value,
        fileIds: uploadedIds,
        onEvent: (evt) => {
          if (evt.type === 'text') {
            if (firstChunk) {
              // 首个字符到达 → 结束思考态，进入说话态
              firstChunk = false
              thinking.value = false
              answering.value = true
              loading.value = false
            }
            raw += evt.content
            const parsed = parseReply(raw)
            updateMessage(replyId, {
              content: parsed.text,
              highlights: extractHighlights(parsed.text),
            })
          } else if (evt.type === 'navigate') {
            navCommand = evt.command
          } else if (evt.type === 'done') {
            if (evt.conversation_id) conversationId.value = evt.conversation_id
          } else if (evt.type === 'error') {
            streamError = evt.message || '知识库检索失败'
          }
        },
      })
    } catch (e) {
      streamError = e instanceof Error ? e.message : '对话服务暂时不可用'
    }

    const parsedFinal = parseReply(raw)
    const finalText = parsedFinal.text
    const command = navCommand ?? parsedFinal.command

    if (streamError) {
      const tip = finalText
        ? `${finalText}\n\n（${streamError}）`
        : `抱歉，${streamError}。请确认后端服务已启动后重试。`
      updateMessage(replyId, { content: tip, highlights: extractHighlights(tip) })
      antMessage.error(streamError)
    } else {
      updateMessage(replyId, {
        content: finalText,
        highlights: extractHighlights(finalText),
        navigateTo: command?.target,
      })
    }

    loading.value = false
    thinking.value = false
    answering.value = false

    commitHistory()

    // ③ AI 回答结束 → 语音播报（同时驱动嘴型）
    if (!streamError && finalText.trim()) {
      ttsSpeak(finalText)
    }

    // ④ 若 Dify 下发了跳转指令，延迟一点执行，让用户先看到回答
    if (command) {
      const target = command.target
      const reason = command.reason
      window.setTimeout(() => navigateTo(target, reason), 900)
    }
  } catch (e) {
    // 附件上传阶段的失败
    const msg = e instanceof Error ? e.message : '附件上传失败'
    antMessage.error(msg)
    loading.value = false
    thinking.value = false
  } finally {
    sending.value = false
  }
}

// ── 生命周期 ──

onMounted(async () => {
  loadHistory()
  try {
    const health = await checkHealth()
    backendOnline.value = health.status === 'ok'
  } catch {
    backendOnline.value = false
  }
})

onBeforeUnmount(() => {
  ttsCancel()
  clearAttachments()
})
</script>

<style scoped src="./ChatPage.css"></style>
