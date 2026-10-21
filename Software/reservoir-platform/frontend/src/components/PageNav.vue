<template>
  <nav class="page-nav glass-panel">
    <ul class="page-nav__list">
      <li v-for="item in ITEMS" :key="item.target">
        <button
          class="page-nav__item"
          :class="{ 'is-active': current === item.target }"
          type="button"
          @click="onNavigate(item.target)"
        >
          <component :is="item.icon" class="page-nav__icon" />
          <span class="page-nav__label">{{ item.title }}</span>
        </button>
      </li>
    </ul>
  </nav>
</template>

<script setup>
import {
  AppstoreOutlined,
  CloudOutlined,
  DashboardOutlined,
  FileProtectOutlined,
  ProfileOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons-vue'

defineProps({
      current: { type: Object, required: true },
      onNavigate: { type: Function, required: true },
    })

/** 平台页面导航项，与路由表一一对应 */
const ITEMS = [
  { target: 'home', title: '智能问答', icon: AppstoreOutlined },
  { target: 'monitor', title: '监测总览', icon: DashboardOutlined },
  { target: 'inspection', title: '巡检台账', icon: ProfileOutlined },
  { target: 'flood', title: '防汛调度', icon: ThunderboltOutlined },
  { target: 'ecology', title: '生态管护', icon: CloudOutlined },
  { target: 'policy', title: '政策文档', icon: FileProtectOutlined },
]
</script>

<style scoped src="./PageNav.css"></style>
