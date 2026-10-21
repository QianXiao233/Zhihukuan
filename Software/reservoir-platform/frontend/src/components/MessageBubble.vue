<template>
  <div class="message-bubble" :class="isUser ? 'is-user' : 'is-assistant'">
    <div class="message-bubble__avatar">
      <RobotOutlined v-if="!isUser" />
      <UserOutlined v-else />
    </div>

    <div class="message-bubble__body">
      <div class="message-bubble__meta">
        <span class="message-bubble__role">{{ isUser ? '我' : 'AI 助手' }}</span>
        <span v-if="message.time" class="message-bubble__time">{{ message.time }}</span>
      </div>

      <div class="message-bubble__text">
        <template v-for="(seg, i) in segments" :key="i">
          <span v-if="seg.danger" class="message-bubble__danger">{{ seg.text }}</span>
          <template v-else>{{ seg.text }}</template>
        </template>
      </div>

      <!-- 多模态附件 -->
      <div v-if="message.attachments?.length" class="message-bubble__attachments">
        <template v-for="file in message.attachments" :key="file.id">
          <img
            v-if="file.kind === 'image' && (file.previewUrl || file.url)"
            class="message-bubble__image"
            :src="file.previewUrl || file.url"
            :alt="file.name"
            title="点击查看原图"
            @click="openImage(file.previewUrl || file.url)"
          />
          <span v-else class="message-bubble__file">
            <FileOutlined />
            <span class="message-bubble__file-name" :title="file.name">{{ file.name }}</span>
            <span class="message-bubble__file-size">{{ formatSize(file.size) }}</span>
          </span>
        </template>
      </div>

      <!-- AI 触发的页面跳转提示 -->
      <button
        v-if="message.navigateTo"
        class="message-bubble__navigate"
        type="button"
        @click="goNavigate"
      >
        <ExportOutlined />
        前往「{{ targetTitle }}」
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { FileOutlined, ExportOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons-vue'

const props = defineProps({
      message: { type: Object, required: true },
    })

const router = useRouter()

/** 页面标识 → 中文名，用于跳转按钮文案 */
const TARGET_TITLE = {
  home: '智能问答',
  monitor: '水库监测总览',
  inspection: '巡检台账',
  policy: '政策文档查阅',
  flood: '防汛调度',
  ecology: '生态管护',
}

const targetTitle = computed(() =>
  props.message.navigateTo ? TARGET_TITLE[props.message.navigateTo] : '',
)

function goNavigate() {
  if (!props.message.navigateTo) return
  void router.push({ name: props.message.navigateTo })
}

/** 图片放大查看：直接新窗口打开，避免额外引入预览组件 */
function openImage(url) {
  window.open(url, '_blank', 'noopener')
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** 把正文按高亮片段切分，避免直接 v-html 注入 */
function buildSegments(content, highlights) {
  if (!highlights || highlights.length === 0) {
    return [{ text: content, danger: false }]
  }

  const marks = highlights
    .map((h) => ({ text: h.text, index: content.indexOf(h.text) }))
    .filter((m) => m.index >= 0 && m.text.length > 0)
    .sort((a, b) => a.index - b.index)

  if (marks.length === 0) {
    return [{ text: content, danger: false }]
  }

  const segments = []
  let cursor = 0

  for (const mark of marks) {
    if (mark.index < cursor) continue
    if (mark.index > cursor) {
      segments.push({ text: content.slice(cursor, mark.index), danger: false })
    }
    segments.push({ text: mark.text, danger: true })
    cursor = mark.index + mark.text.length
  }

  if (cursor < content.length) {
    segments.push({ text: content.slice(cursor), danger: false })
  }
  return segments
}

const segments = computed(() => buildSegments(props.message.content, props.message.highlights))
const isUser = computed(() => props.message.role === 'user')
</script>

<style scoped src="./MessageBubble.css"></style>
