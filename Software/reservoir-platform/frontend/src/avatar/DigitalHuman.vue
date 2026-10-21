<template>
  <div class="digital-human">
    <div class="digital-human__stage">
      <canvas ref="canvasRef" class="digital-human__canvas"></canvas>
      <div class="digital-human__halo" :class="{ 'is-speaking': speaking }"></div>
    </div>

    <div class="digital-human__caption">
      <div class="digital-human__status">
        <span class="digital-human__dot" :class="{ 'is-speaking': speaking }"></span>
        <span class="digital-human__status-text">{{ statusText }}</span>
      </div>
      <h2 class="digital-human__name">{{ DIGITAL_HUMAN_TITLE }}</h2>
      <p class="digital-human__desc">{{ DIGITAL_HUMAN_SUBTITLE }}</p>

      <!-- 手动触发动作，便于演示与自测 -->
      <div class="digital-human__actions">
        <button
          v-for="item in GESTURE_BUTTONS"
          :key="item.gesture"
          class="digital-human__action"
          type="button"
          :title="item.title"
          @click="playGesture(item.gesture)"
        >
          <component :is="item.icon" />
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { CommentOutlined, BulbOutlined, SmileOutlined, SoundOutlined } from '@ant-design/icons-vue'
import { RobotRenderer } from './RobotRenderer.js'
import { DIGITAL_HUMAN_SUBTITLE, DIGITAL_HUMAN_TITLE } from '../mockData.js'

const props = defineProps({
      /** 由父组件控制：AI 正在输出/朗读时为 true */
      speaking: { type: Boolean, required: true },
      /** 期待 AI 思考时（请求发出到首字返回之间）为 true */
      thinking: { type: Boolean, required: false },
    })

const canvasRef = ref(null)
let renderer = null
let resizeObserver = null

const handleResize = () => renderer?.resize()

/** 页面不可见时暂停渲染循环，避免后台空转 */
function handleVisibility() {
  if (!renderer) return
  if (document.hidden) renderer.stop()
  else renderer.start()
}

/** 播放一次性动作（挥手/点头） */
function playGesture(gesture) {
  if (gesture === 'wave' || gesture === 'nod') renderer?.playGesture(gesture)
  else renderer?.setGesture(gesture)
}

/** 供父组件调用的一次性动作入口 */
function wave() {
  renderer?.playGesture('wave')
}

function nod() {
  renderer?.playGesture('nod')
}

defineExpose({ wave, nod, playGesture })

const GESTURE_BUTTONS = [
  { gesture: 'wave', title: '挥手', icon: SmileOutlined },
  { gesture: 'nod', title: '点头', icon: CommentOutlined },
  { gesture: 'thinking', title: '思考', icon: BulbOutlined },
  { gesture: 'talking', title: '讲解', icon: SoundOutlined },
]

const statusText = computed(() => {
  if (props.speaking) return '正在为您播报…'
  if (props.thinking) return '正在思考…'
  return '在线值守中'
})

onMounted(() => {
  const canvas = canvasRef.value
  if (!canvas) return

  renderer = new RobotRenderer(canvas)
  renderer.setSpeaking(props.speaking)
  if (props.thinking) renderer.setGesture('thinking')
  renderer.start()

  resizeObserver = new ResizeObserver(handleResize)
  resizeObserver.observe(canvas)
  window.addEventListener('resize', handleResize)
  document.addEventListener('visibilitychange', handleVisibility)
})

watch(
  () => props.speaking,
  (v) => renderer?.setSpeaking(v),
)

// 思考状态优先于待机，但不打断已经在说话的状态
watch(
  () => props.thinking,
  (v) => {
    if (props.speaking) return
    renderer?.setGesture(v ? 'thinking' : 'idle')
  },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  resizeObserver = null
  window.removeEventListener('resize', handleResize)
  document.removeEventListener('visibilitychange', handleVisibility)
  renderer?.dispose()
  renderer = null
})
</script>

<style scoped src="./DigitalHuman.css"></style>
