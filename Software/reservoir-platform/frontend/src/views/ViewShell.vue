<template>
  <div class="platform-page" :class="[`font-${uiPreferences.fontSize}`, { 'is-compact': uiPreferences.compact }]">
    <aside class="platform-sidebar">
      <div class="platform-brand">
        <div class="platform-brand__mark"><span></span><span></span><span></span></div>
        <div>
          <strong>智御安澜</strong>
          <small>水库数字化运营工作台</small>
        </div>
      </div>

      <div ref="damSelectorRoot" class="dam-selector" @keydown.esc.stop="damMenuOpen = false">
        <button class="platform-selector" type="button" aria-haspopup="listbox" :aria-expanded="damMenuOpen" title="切换当前管理水库" @click="damMenuOpen = !damMenuOpen">
          <span class="platform-selector__dot"></span>
          <span class="platform-selector__copy">
            <small>当前管理对象</small>
            <strong>{{ currentDamName }}</strong>
          </span>
          <i class="platform-selector__chevron" :class="{ 'is-open': damMenuOpen }" aria-hidden="true"></i>
        </button>
        <div v-if="damMenuOpen" class="dam-selector__menu" role="listbox" aria-label="选择管理水库">
          <div class="dam-selector__menu-title">切换管理对象</div>
          <button v-for="dam in dams" :key="dam.damId" class="dam-selector__option" :class="{ 'is-selected': String(dam.damId) === selectedDamId }" type="button" role="option" :aria-selected="String(dam.damId) === selectedDamId" @click="chooseDam(dam.damId)">
            <span class="dam-selector__option-mark"><i></i></span>
            <span>{{ dam.damName || `水库 #${dam.damId}` }}</span>
            <b v-if="String(dam.damId) === selectedDamId" aria-hidden="true">✓</b>
          </button>
          <div v-if="!dams.length" class="dam-selector__empty">暂无水库档案</div>
        </div>
      </div>

      <nav class="platform-nav" aria-label="平台功能导航">
        <template v-for="group in NAV_GROUPS" :key="group.label">
          <p class="platform-nav__label">{{ group.label }}</p>
          <button v-for="item in group.items.filter(item => item.name !== 'users' || isAdmin)" :key="item.name" type="button" class="platform-nav__item" :class="{ 'is-active': isActive(item) }" @click="navigate(item.name)">
            <component :is="item.icon" class="platform-nav__icon" />
            <span>{{ item.title }}</span>
            <i v-if="item.name === 'notifications' && unreadCount" class="platform-nav__badge">{{ unreadCount > 99 ? '99+' : unreadCount }}</i>
          </button>
        </template>
      </nav>

      <div class="platform-sidebar__footer">
        <div class="platform-health"><i :class="runtime ? (runtime.database ? 'is-online' : 'is-offline') : runtimeLoaded ? 'is-offline' : 'is-pending'"></i><span>{{ runtime ? (runtime.database ? '数据库连接正常' : '数据库连接异常') : runtimeLoaded ? '数据库状态不可用' : '正在检测数据库' }}</span><small>平台设备台账 {{ runtime?.deviceCount ?? '—' }} 台</small></div>
        <button type="button" class="platform-help" @click="navigate('home')">
          <QuestionCircleOutlined />
          <span>需要帮助？询问 AI 助手</span>
        </button>
      </div>
    </aside>

    <section class="platform-content">
      <header class="platform-topbar">
        <div class="platform-breadcrumb">
          <span>{{ currentDamName }}</span><span class="platform-breadcrumb__slash">/</span><strong>{{ title }}</strong>
        </div>
        <div class="platform-topbar__right">
          <span class="platform-online" :class="{ 'is-offline': runtimeLoaded && (!runtime || !runtime.database) }"><i></i>{{ runtime ? (runtime.database ? '后端服务已连接' : '后端服务连接异常') : runtimeLoaded ? '后端服务状态不可用' : '正在检测后端服务' }}</span>
          <button type="button" class="platform-icon-button" aria-label="通知" title="消息通知" @click="navigate('notifications')">
            <BellOutlined /><b v-if="unreadCount">{{ unreadCount > 99 ? '99+' : unreadCount }}</b>
          </button>
          <span class="platform-time">{{ currentTime }}</span>
          <button type="button" class="platform-user" title="退出登录" @click="logout"><span class="platform-user__avatar">管</span>{{ username }} <DownOutlined /></button>
        </div>
      </header>

      <main class="platform-main">
        <div class="platform-heading">
          <div>
            <div class="platform-heading__eyebrow">水库数字化运营 · {{ title }}</div>
            <h1><component :is="icon" />{{ title }}</h1>
          </div>
          <span class="platform-tag">{{ tag }}</span>
        </div>
        <div class="platform-body">
          <slot />
        </div>
      </main>
    </section>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AppstoreOutlined,
  BankOutlined,
  BellOutlined,
  CloudOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DownOutlined,
  FileProtectOutlined,
  FundProjectionScreenOutlined,
  ProfileOutlined,
  QuestionCircleOutlined,
  SettingOutlined,
  SafetyCertificateOutlined,
  SlidersOutlined,
  TeamOutlined,
  ToolOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'
import { clearAuth, validateToken } from '../api/auth.js'
import { getRuntime, unreadMessageCount } from '../api/manageApi.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'

defineProps({
  title: { type: String, required: true },
  tag: { type: String, required: true },
  icon: { type: [Object, Function], required: true },
})

const uiPreferences = ref({ compact: false, fontSize: 'normal' })
function updateUiPreferences() { uiPreferences.value = { compact: localStorage.getItem('platform.compact') === 'true', fontSize: localStorage.getItem('platform.fontSize') || 'normal' }; clearInterval(notificationTimer); notificationTimer = undefined; if(localStorage.getItem('platform.autoRefresh') !== 'false') notificationTimer = window.setInterval(refreshUnread, 30000) }
const route = useRoute()
const router = useRouter()
const username = localStorage.getItem('username') || '管理员'
const { dams, selectedDamId, currentDamName, loadDams, selectDam } = useCurrentDam()
const damSelectorRoot = ref(null)
const damMenuOpen = ref(false)
const isAdmin = ref([0,3].includes(Number(localStorage.getItem('level') ?? 1)) || Number(localStorage.getItem('level')) > 3)
const currentTime = ref('')
const unreadCount = ref(0)
const runtime = ref(null)
const runtimeLoaded = ref(false)
let clockTimer
let notificationTimer

function updateClock() {
  currentTime.value = new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()).replaceAll('/', '-')
}

async function refreshUnread() {
  try { unreadCount.value = await unreadMessageCount() } catch { /* 网络异常时保留上次结果 */ }
}

async function refreshRuntime() {
  try { runtime.value = (await getRuntime()).data }
  catch { runtime.value = null }
  finally { runtimeLoaded.value = true }
}

function chooseDam(damId) {
  selectDam(damId)
  damMenuOpen.value = false
}

function closeDamMenuOnOutside(event) {
  if (!damSelectorRoot.value?.contains(event.target)) damMenuOpen.value = false
}

onMounted(() => {
  updateClock()
  updateUiPreferences()
  window.addEventListener('platform-preferences', updateUiPreferences)
  clockTimer = window.setInterval(updateClock, 1000)
  void refreshUnread()
  void refreshRuntime()
  void loadDams()
  document.addEventListener('click', closeDamMenuOnOutside)
  void validateToken(localStorage.getItem('token')).then(identity => { if(identity.success){ localStorage.setItem('level', String(identity.level)); isAdmin.value = identity.level === 0 || identity.level >= 3 } }).catch(() => {})
})
onBeforeUnmount(() => { window.removeEventListener('platform-preferences', updateUiPreferences); document.removeEventListener('click', closeDamMenuOnOutside); clearInterval(clockTimer); clearInterval(notificationTimer) })

const NAV_GROUPS = [
  {
    label: '业务功能',
    items: [
      { name: 'monitor', title: '运营总览', icon: AppstoreOutlined },
      { name: 'monitor-detail', title: '实时监测', icon: DashboardOutlined },
      { name: 'inspection', title: '巡检台账', icon: ProfileOutlined },
      { name: 'flood', title: '防汛调度', icon: ThunderboltOutlined },
      { name: 'ecology', title: '生态管护', icon: CloudOutlined },
      { name: 'boat', title: '无人艇中心', icon: FundProjectionScreenOutlined },
    ],
  },
  {
    label: '管理中心',
    items: [
      { name: 'dam', title: '库区档案', icon: BankOutlined },
      { name: 'devices', title: '设备管理', icon: ToolOutlined },
      { name: 'parameters', title: '监测参数设置', icon: SlidersOutlined },
      { name: 'users', title: '用户与权限', icon: TeamOutlined },
      { name: 'data-maintenance', title: '数据维护', icon: DatabaseOutlined },
      { name: 'operations', title: '运行与审计', icon: SafetyCertificateOutlined },
    ],
  },
  {
    label: '平台服务',
    items: [
      { name: 'notifications', title: '消息通知', icon: BellOutlined },
      { name: 'policy', title: '政策文档', icon: FileProtectOutlined },
      { name: 'settings', title: '系统设置', icon: SettingOutlined },
      { name: 'home', title: 'AI 助手', icon: QuestionCircleOutlined },
    ],
  },
]

function isActive(item) {
  return route.name === item.name
}

function navigate(name) {
  void router.push({ name })
}

function logout() {
  clearAuth()
  void router.replace({ name: 'login' })
}
</script>

<style scoped src="./ViewShell.css"></style>


