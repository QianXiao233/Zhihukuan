<template>
  <section class="history-panel panel-card">
    <header class="panel-head">
      <HistoryOutlined class="panel-head__icon" />
      <h3 class="panel-head__title">历史对话</h3>
      <Popconfirm
        v-if="history.length > 0"
        title="确定清空全部历史记录？"
        ok-text="清空"
        cancel-text="取消"
        @confirm="onClear"
      >
        <button class="history-panel__clear" type="button">
          <DeleteOutlined />
        </button>
      </Popconfirm>
    </header>

    <ul v-if="history.length > 0" class="history-panel__list">
      <li v-for="item in history" :key="item.id" class="history-panel__item">
        <span class="history-panel__dot"></span>
        <span class="history-panel__title" :title="item.title">{{ item.title }}</span>
        <span class="history-panel__time">{{ item.time }}</span>
      </li>
    </ul>

    <div v-else class="history-panel__empty">
      <InboxOutlined />
      <span>暂无历史记录</span>
    </div>
  </section>
</template>

<script setup>
import { Popconfirm } from 'ant-design-vue'
import { DeleteOutlined, HistoryOutlined, InboxOutlined } from '@ant-design/icons-vue'

defineProps({
      history: { type: Array, required: true },
      onClear: { type: Function, required: true },
    })
</script>

<style scoped src="./HistoryPanel.css"></style>
