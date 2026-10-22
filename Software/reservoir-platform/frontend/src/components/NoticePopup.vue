<template>
  <Teleport to="body">
    <div v-if="noticeState.current" class="notice-mask">
      <section
        class="notice-modal"
        role="alertdialog"
        aria-modal="true"
        :aria-label="noticeState.current.title"
        @keydown.esc.prevent.stop
      >
        <header class="notice-modal__head">
          <span class="notice-badge" :class="`level-${noticeState.current.level}`">
            <WarningOutlined v-if="noticeState.current.level >= 2" />
            <InfoCircleOutlined v-else />
          </span>
          <div class="notice-modal__title">
            <small>{{ levelText(noticeState.current.level) }} · {{ formatTime(noticeState.current.time) }}</small>
            <h2>{{ noticeState.current.title }}</h2>
          </div>
        </header>

        <p class="notice-modal__body">{{ noticeState.current.content }}</p>

        <footer class="notice-modal__foot">
          <span v-if="noticeState.queue.length" class="notice-pending">还有 {{ noticeState.queue.length }} 条待确认</span>
          <div class="notice-actions">
            <button class="plain-btn" type="button" @click="openList">查看通知</button>
            <button ref="confirmButton" class="primary-btn" type="button" @click="confirmNotice">我知道了</button>
          </div>
        </footer>
      </section>
    </div>

    <div class="toast-stack" aria-live="polite">
      <article
        v-for="toast in noticeState.toasts"
        :key="toast.toastId"
        class="notice-toast"
        :class="`level-${toast.level}`"
      >
        <span class="toast-dot"></span>
        <div>
          <strong>{{ toast.title }}</strong>
          <p>{{ toast.content }}</p>
        </div>
      </article>
    </div>
  </Teleport>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons-vue'
import { confirmNotice, noticeState } from '../utils/noticeChannel.js'

const router = useRouter()
const confirmButton = ref(null)

const LEVEL_TEXT = { 3: '严重通知', 2: '警告通知', 1: '提示通知' }
const levelText = (level) => LEVEL_TEXT[level] || '平台通知'

function formatTime(value) {
  if (!value) return '刚刚'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '刚刚'
  return date.toLocaleString('zh-CN', { hour12: false })
}

function openList() {
  confirmNotice()
  void router.push({ name: 'notifications' })
}

watch(
  () => noticeState.current,
  async (current) => {
    document.body.style.overflow = current ? 'hidden' : ''
    if (current) {
      await nextTick()
      confirmButton.value?.focus()
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
})
</script>

<style scoped>
.notice-mask{position:fixed;inset:0;z-index:200;display:flex;align-items:center;justify-content:center;padding:24px;background:rgba(12,34,52,.52);backdrop-filter:blur(4px);animation:notice-fade .18s ease}
.notice-modal{width:min(560px,100%);overflow:hidden;border-radius:18px;background:#fff;box-shadow:0 30px 80px rgba(6,30,48,.35);animation:notice-rise .22s ease}
.notice-modal__head{display:flex;gap:13px;padding:22px 24px 0}
.notice-badge{display:flex;align-items:center;justify-content:center;flex:0 0 44px;height:44px;border-radius:13px;font-size:21px}
.notice-badge.level-3{background:#fff0ee;color:#d5574f}
.notice-badge.level-2{background:#fff6e7;color:#d29133}
.notice-badge.level-1{background:#eaf6ff;color:#2685c5}
.notice-modal__title{min-width:0;flex:1}
.notice-modal__title small{display:block;color:#93a5b2;font-size:11px;letter-spacing:.02em}
.notice-modal__title h2{margin:4px 0 0;color:#1b3e5c;font-size:17px;line-height:1.4;overflow-wrap:anywhere}
.notice-modal__body{margin:16px 24px 0;padding:14px 16px;border-radius:11px;background:#f7fbfe;color:#48657c;font-size:13px;line-height:1.85;white-space:pre-wrap;overflow-wrap:anywhere;max-height:46vh;overflow:auto}
.notice-modal__foot{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:18px 24px 22px}
.notice-pending{color:#93a5b2;font-size:11px}
.notice-actions{display:flex;gap:9px;margin-left:auto}
.plain-btn,.primary-btn{height:36px;padding:0 16px;border-radius:9px;font-size:12px;cursor:pointer;transition:.15s}
.plain-btn{border:1px solid #d7e5ef;background:#fff;color:#4a6b82}
.plain-btn:hover{border-color:#9cc4e0;color:#1679d1}
.primary-btn{border:0;background:#1679d1;color:#fff;box-shadow:0 6px 14px rgba(22,121,209,.22)}
.primary-btn:hover{background:#1269ba}
.primary-btn:focus-visible,.plain-btn:focus-visible{outline:2px solid #7db6e0;outline-offset:2px}
.toast-stack{position:fixed;top:74px;right:24px;z-index:190;display:flex;flex-direction:column;gap:9px;width:min(330px,calc(100vw - 40px));pointer-events:none}
.notice-toast{display:flex;gap:9px;padding:12px 14px;border:1px solid #e2ebf3;border-left:3px solid #7db6e0;border-radius:10px;background:#fff;box-shadow:0 12px 30px rgba(20,60,90,.16);animation:toast-in .2s ease}
.notice-toast.level-3{border-left-color:#d5574f}
.notice-toast.level-2{border-left-color:#d29133}
.notice-toast.level-1{border-left-color:#2685c5}
.toast-dot{flex:0 0 8px;width:8px;height:8px;margin-top:5px;border-radius:50%;background:#7db6e0}
.notice-toast.level-3 .toast-dot{background:#d5574f}
.notice-toast.level-2 .toast-dot{background:#d29133}
.notice-toast strong{display:block;color:#294b66;font-size:12px}
.notice-toast p{margin:3px 0 0;color:#7b8f9e;font-size:11px;line-height:1.6;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
@keyframes notice-fade{from{opacity:0}to{opacity:1}}
@keyframes notice-rise{from{opacity:0;transform:translateY(12px) scale(.98)}to{opacity:1;transform:none}}
@keyframes toast-in{from{opacity:0;transform:translateX(14px)}to{opacity:1;transform:none}}
</style>
