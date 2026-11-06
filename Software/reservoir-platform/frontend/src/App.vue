<template>
  <router-view v-slot="{ Component }">
    <transition name="page-fade" mode="out-in">
      <component :is="Component" />
    </transition>
  </router-view>
  <NoticePopup />
  <!-- 开闸确认弹窗挂在根节点：任意页面都要能收到，不能因为在别的页就错过 -->
  <GlobalApprovalModal />
</template>

<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import NoticePopup from './components/NoticePopup.vue'
import GlobalApprovalModal from './components/GlobalApprovalModal.vue'
import { startNoticeChannel, stopNoticeChannel } from './utils/noticeChannel.js'

// 登录后订阅平台通知频道；多标签页登录/退出时同步连接状态
function handleStorage(event) {
  if (event.key !== 'token') return
  if (event.newValue) startNoticeChannel()
  else stopNoticeChannel()
}

onMounted(() => {
  startNoticeChannel()
  window.addEventListener('storage', handleStorage)
})

onBeforeUnmount(() => {
  window.removeEventListener('storage', handleStorage)
})
</script>

<style>
/* 页面切换过渡 */
.page-fade-enter-active,
.page-fade-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease;
}

.page-fade-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.page-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
