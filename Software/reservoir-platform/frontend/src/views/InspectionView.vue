<template>
  <ViewShell title="巡检台账" tag="巡检数据尚未接入数据库" :icon="ProfileOutlined">
    <section class="view-card">
      <div class="view-card__toolbar"><h2 class="view-card__title"><ProfileOutlined /> 巡查记录</h2></div>
      <ul class="view-list">
        <li v-for="item in filteredRecords" :key="item.id" class="view-list__item">
          <div class="view-list__head">
            <span class="view-list__title">{{ item.title }}</span>
            <span class="view-status" :class="`view-status--${item.state}`">{{ item.stateText }}</span>
            <span class="view-list__time">{{ item.time }}</span>
          </div>
          <p class="view-list__desc">{{ item.desc }}</p>
        </li>
        <li v-if="!filteredRecords.length" class="view-list__item inspection-empty">巡检台账尚未接入 MySQL 数据表，当前不展示演示记录。</li>
      </ul>
    </section>

    <section class="view-card">
      <h2 class="view-card__title"><SafetyCertificateOutlined /> 隐患整改进度</h2>
      <table class="view-table">
        <thead>
          <tr>
            <th>隐患编号</th>
            <th>部位</th>
            <th>问题描述</th>
            <th>责任人</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in HAZARDS" :key="row.no">
            <td>{{ row.no }}</td>
            <td>{{ row.part }}</td>
            <td>{{ row.desc }}</td>
            <td>{{ row.owner }}</td>
            <td>
              <span class="view-status" :class="`view-status--${row.state}`">{{ row.stateText }}</span>
            </td>
          </tr>
          <tr v-if="!HAZARDS.length"><td colspan="5" class="inspection-empty">隐患整改尚未接入 MySQL 数据表，当前不展示演示记录。</td></tr>
        </tbody>
      </table>
    </section>
  </ViewShell>
</template>

<script setup>
import { computed } from 'vue'
import { ProfileOutlined, SafetyCertificateOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'

const RECORDS = []
const HAZARDS = []

const filteredRecords = computed(() => RECORDS)
</script>

<style scoped>
.view-card__toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px}.view-card__toolbar .view-card__title{margin-bottom:14px}
.inspection-empty{padding:18px;color:#90a2b0;font-size:11px;text-align:center}
</style>
