<template>
  <div ref="listRef" class="message-list">
    <div class="message-list__inner">
      <MessageBubble v-for="message in messages" :key="message.id" :message="message" />

      <div v-if="loading" class="message-list__loading">
        <span class="message-list__dots">
          <i></i><i></i><i></i>
        </span>
        <span class="message-list__loading-text">{{ loadingText }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import MessageBubble from './MessageBubble.vue'

const props = defineProps({
  messages: { type: Array, required: true },
  loading: { type: Boolean, required: false, default: false },
  loadingText: {
    type: String,
    required: false,
    default: '正在检索水利知识库，请稍候……',
  },
})

const listRef = ref(null)

/** 新消息自动滚到底部 */
function scrollToBottom() {
  const el = listRef.value
  if (!el) return
  el.scrollTop = el.scrollHeight
}

watch(
  () => [props.messages.length, props.messages[props.messages.length - 1]?.content, props.loading],
  () => {
    void nextTick(scrollToBottom)
  },
  { flush: 'post' },
)
</script>

<style scoped src="./MessageList.css"></style>
