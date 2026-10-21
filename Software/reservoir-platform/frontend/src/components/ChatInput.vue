<template>
  <div class="chat-input">
    <!-- 待发送附件预览 -->
    <div v-if="attachments.length > 0" class="chat-input__preview">
      <div v-for="file in attachments" :key="file.id" class="chat-input__preview-item">
        <img
          v-if="file.kind === 'image' && file.previewUrl"
          class="chat-input__preview-thumb"
          :src="file.previewUrl"
          :alt="file.name"
        />
        <FileOutlined v-else />
        <span class="chat-input__preview-name" :title="file.name">{{ file.name }}</span>
        <button
          class="chat-input__preview-remove"
          type="button"
          title="移除"
          @click="removeAttachment(file.id)"
        >
          <CloseOutlined />
        </button>
      </div>
    </div>

    <div class="chat-input__box">
      <textarea
        ref="textareaRef"
        class="chat-input__textarea"
        :value="value"
        :maxlength="MAX_LENGTH"
        placeholder="请输入您的问题，或上传图片 / 文档提问…"
        rows="1"
        @input="handleInput"
        @keydown="handleKeydown"
      />

      <div class="chat-input__tools">
        <Tooltip title="上传图片或文档" placement="top">
          <button class="chat-input__icon-btn" type="button" @click="pickFile">
            <PaperClipOutlined />
          </button>
        </Tooltip>

        <Tooltip :title="micTitle" placement="top">
          <button
            class="chat-input__icon-btn chat-input__mic"
            :class="{ 'is-recording': recording }"
            type="button"
            @click="handleMic"
          >
            <span v-if="recording" class="chat-input__wave"><i></i><i></i><i></i></span>
            <AudioOutlined v-else />
          </button>
        </Tooltip>

        <span class="chat-input__count" :class="{ 'is-limit': value.length >= MAX_LENGTH }">
          {{ value.length }}/{{ MAX_LENGTH }}
        </span>

        <Button type="primary" :disabled="!canSend" :loading="busy" @click="onSend">
          <template #icon><SendOutlined /></template>
          发送
        </Button>
      </div>
    </div>

    <p class="chat-input__hint">
      按 Enter 发送，Shift + Enter 换行{{ asrSupported ? '；也可点击麦克风语音提问' : '' }}
    </p>

    <input
      ref="fileInputRef"
      class="chat-input__file-input"
      type="file"
      multiple
      :accept="ACCEPT"
      @change="handleFileChange"
    />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Button, Tooltip, message as antMessage } from 'ant-design-vue'
import {
  AudioOutlined,
  CloseOutlined,
  FileOutlined,
  PaperClipOutlined,
  SendOutlined,
} from '@ant-design/icons-vue'
import { useSpeechRecognition } from '../voice/useSpeechRecognition.js'

/** 输入字数上限 */
const MAX_LENGTH = 1000
/** 单文件大小上限 10MB */
const MAX_FILE_SIZE = 10 * 1024 * 1024
/** 允许的文件类型：图片 + 常见文档 */
const ACCEPT = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
  'application/pdf',
  'application/msword',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
  'text/markdown',
].join(',')

const props = defineProps({
      value: { type: String, required: true },
      attachments: { type: Array, required: true },
      busy: { type: Boolean, required: false },
      onChange: { type: Function, required: true },
      onAttach: { type: Function, required: true },
      onRemoveAttachment: { type: Function, required: true },
      onSend: { type: Function, required: true },
    })

const textareaRef = ref(null)
const fileInputRef = ref(null)

const canSend = computed(
  () => props.value.trim().length > 0 || props.attachments.length > 0,
)

const { recording, supported: asrSupported, toggle: toggleRecord, error: asrError } =
  useSpeechRecognition({
    // 识别结果填入输入框，由用户确认后再发送
    onResult: (text) => props.onChange(text),
  })

const micTitle = computed(() => {
  if (!asrSupported.value) return '当前浏览器不支持录音，请使用 Chrome / Edge'
  return recording.value ? '点击结束录音' : '点击开始语音输入'
})

function handleInput(e) {
  const target = e.target
  props.onChange(target.value)
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    if (canSend.value) props.onSend()
  }
}

function handleMic() {
  if (!asrSupported.value) {
    antMessage.warning('当前浏览器不支持录音，请使用 Chrome / Edge')
    return
  }
  void toggleRecord()
}

function pickFile() {
  fileInputRef.value?.click()
}

/** 读取选中的文件为待上传附件 */
function handleFileChange(e) {
  const input = e.target
  const files = Array.from(input.files ?? [])
  input.value = '' // 允许重复选择同一文件

  const accepted = []

  for (const file of files) {
    if (file.size > MAX_FILE_SIZE) {
      antMessage.warning(`「${file.name}」超过 10MB，已跳过`)
      continue
    }
    const isImage = file.type.startsWith('image/')
    accepted.push({
      id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
      name: file.name,
      size: file.size,
      mimeType: file.type || 'application/octet-stream',
      kind: isImage ? 'image' : 'document',
      file,
      previewUrl: isImage ? URL.createObjectURL(file) : undefined,
    })
  }

  if (accepted.length > 0) props.onAttach(accepted)
}

function removeAttachment(id) {
  const target = props.attachments.find((a) => a.id === id)
  if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl)
  props.onRemoveAttachment(id)
}

// 语音识别失败时给出友好提示
watch(asrError, (msg) => {
  if (msg) antMessage.error(msg)
})
</script>

<style scoped src="./ChatInput.css"></style>
