<template>
  <section class="quick-links panel-card">
    <header class="panel-head">
      <AppstoreOutlined class="panel-head__icon" />
      <h3 class="panel-head__title">快捷跳转</h3>
    </header>

    <div class="quick-links__grid">
      <button
        v-for="link in links"
        :key="link.id"
        class="quick-links__card"
        type="button"
        @click="onLinkClick?.(link)"
      >
        <span class="quick-links__icon">
          <component :is="ICON_MAP[link.icon] ?? AppstoreOutlined" />
        </span>
        <span class="quick-links__title">{{ link.title }}</span>
        <span class="quick-links__desc">{{ link.description }}</span>
      </button>
    </div>
  </section>
</template>

<script setup>
import {
  AppstoreOutlined,
  DashboardOutlined,
  ProfileOutlined,
  ReadOutlined,
} from '@ant-design/icons-vue'

defineProps({
      links: { type: Array, required: true },
      onLinkClick: { type: Function, required: false },
    })

/** 卡片图标映射（规范里的 icon 字符串 → antd 图标，统一线性风格） */
const ICON_MAP = {
  monitor: DashboardOutlined,
  ledger: ProfileOutlined,
  document: ReadOutlined,
}
</script>

<style scoped src="./QuickLinks.css"></style>
