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

      <!-- 用户输入按纯文本展示；AI 回答渲染 Markdown（已消毒，见 utils/markdown.js） -->
      <div v-if="isUser" class="message-bubble__text">{{ message.content }}</div>
      <div
        v-else
        class="message-bubble__text message-bubble__markdown"
        v-html="renderedMarkdown"
      ></div>

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

      <!-- AI 建议的页面入口：只展示按钮，用户点了才跳转 -->
      <button
        v-if="message.navigateTo"
        class="message-bubble__navigate"
        type="button"
        :aria-label="`打开${targetTitle}`"
        @click="goNavigate"
      >
        <span class="message-bubble__navigate-icon"><ExportOutlined /></span>
        <span class="message-bubble__navigate-body">
          <span class="message-bubble__navigate-title">前往「{{ targetTitle }}」</span>
          <span v-if="message.navigateReason" class="message-bubble__navigate-reason">
            {{ message.navigateReason }}
          </span>
        </span>
        <span class="message-bubble__navigate-hint">点击打开</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { FileOutlined, ExportOutlined, RobotOutlined, UserOutlined } from '@ant-design/icons-vue'
import { targetTitle as titleOf } from '../router/targets.js'
import { renderMarkdown } from '../utils/markdown.js'

const props = defineProps({
      message: { type: Object, required: true },
    })
const emit = defineEmits(['navigate'])

/** 页面标识 → 中文名，用于跳转按钮文案 */
const targetTitle = computed(() =>
  props.message.navigateTo ? titleOf(props.message.navigateTo) : '',
)

/** 只响应用户点击，不做任何自动跳转 */
function goNavigate() {
  if (!props.message.navigateTo) return
  emit('navigate', {
    target: props.message.navigateTo,
    reason: props.message.navigateReason || '',
  })
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

/** AI 回答渲染成 Markdown；内容已消毒，避免直接信任模型输出 */
const renderedMarkdown = computed(() => renderMarkdown(props.message.content))
const isUser = computed(() => props.message.role === 'user')
</script>

<style scoped src="./MessageBubble.css"></style>
