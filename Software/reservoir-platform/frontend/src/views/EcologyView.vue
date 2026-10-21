<template>
  <ViewShell title="生态管护" :tag="realtime ? 'RTU 水环境数据已接收' : mqttConnected ? 'MQTT 已连接 · 等待 RTU 状态' : '等待 MQTT 接入'" :icon="CloudOutlined">
    <section class="view-card">
      <h2 class="view-card__title"><CloudOutlined /> 水情与水环境实时数据</h2>
      <div class="view-metrics">
        <div v-for="metric in metrics" :key="metric.label" class="view-metric">
          <div class="view-metric__label">{{ metric.label }}</div>
          <div class="view-metric__value">{{ metric.value }}<span class="view-metric__unit">{{ metric.unit }}</span></div>
          <div class="view-metric__hint">{{ metric.hint }}</div>
        </div>
      </div>
    </section>

    <section class="view-card">
      <h2 class="view-card__title"><ExperimentOutlined /> 平台监测阈值</h2>
      <table class="view-table">
        <thead><tr><th>指标</th><th>实测值</th><th>数据库阈值</th><th>参数类型</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="row in waterRows" :key="row.code">
            <td>{{ row.name }}</td><td>{{ row.value }}</td><td>{{ row.threshold }}</td><td>{{ row.type }}</td>
            <td><span class="view-status" :class="`view-status--${row.state}`">{{ row.stateText }}</span></td>
          </tr>
        </tbody>
      </table>
      <p v-if="paramError" class="data-error">监测阈值读取失败：{{ paramError }}</p>
    </section>

    <section class="view-card data-boundary">
      <h2 class="view-card__title"><CloudOutlined /> 当前数据范围</h2>
      <p>RTU 当前上报水位、液温、pH、ORP 和闸门状态；监测阈值是平台共用配置。RTU 未上报入库/出库流量或天气预报，因此本页不展示放流量、降雨预警等推算数据。</p>
    </section>
  </ViewShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { CloudOutlined, ExperimentOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { useReservoirMqtt } from '../composables/useReservoirMqtt.js'
import { listParams } from '../api/manageApi.js'

const { realtime, mqttConnected } = useReservoirMqtt()
const params = ref([])
const paramError = ref('')

const metrics = computed(() => [
  { label: '当前水位', value: realtime.value?.level == null ? '—' : Number(realtime.value.level).toFixed(2), unit: 'm', hint: 'MQTT · level' },
  { label: '液温', value: realtime.value?.temp == null ? '—' : Number(realtime.value.temp).toFixed(1), unit: '℃', hint: 'MQTT · temp' },
  { label: 'pH', value: realtime.value?.ph == null ? '—' : Number(realtime.value.ph).toFixed(2), unit: '', hint: 'MQTT · ph' },
  { label: 'ORP', value: realtime.value?.orp == null ? '—' : Number(realtime.value.orp).toFixed(0), unit: 'mV', hint: 'MQTT · orp' },
])

const definitions = [
  { code: 'water_level', aliases: ['water_level', 'level'], name: '水位', unit: 'm', field: 'level', digits: 2, type: '水情' },
  { code: 'temperature', aliases: ['temperature', 'temp'], name: '液温', unit: '℃', field: 'temp', digits: 1, type: '水质' },
  { code: 'ph', aliases: ['ph'], name: 'pH', unit: '', field: 'ph', digits: 2, type: '水质' },
  { code: 'orp', aliases: ['orp'], name: 'ORP', unit: 'mV', field: 'orp', digits: 0, type: '水质' },
]

const waterRows = computed(() => definitions.map((definition) => {
  const parameter = params.value.find((item) => definition.aliases.includes(String(item.paramCode || '').toLowerCase()))
  const reading = realtime.value?.[definition.field]
  const value = reading == null ? null : Number(reading)
  const low = Number(parameter?.paramLowValue), high = Number(parameter?.paramHighValue)
  const hasLow = parameter?.paramLowValue !== null && parameter?.paramLowValue !== undefined && parameter.paramLowValue !== '' && Number.isFinite(low)
  const hasHigh = parameter?.paramHighValue !== null && parameter?.paramHighValue !== undefined && parameter.paramHighValue !== '' && Number.isFinite(high)
  const hasThreshold = hasLow || hasHigh
  const outside = value !== null && hasThreshold && ((hasLow && value < low) || (hasHigh && value > high))
  return {
    ...definition,
    name: parameter?.paramName || definition.name,
    value: value === null ? '等待数据' : `${value.toFixed(definition.digits)}${definition.unit ? ` ${definition.unit}` : ''}`,
    threshold: hasThreshold ? `${parameter.paramLowValue ?? '—'} ~ ${parameter.paramHighValue ?? '—'}${definition.unit ? ` ${definition.unit}` : ''}` : '未配置',
    type: parameter?.paramType || definition.type,
    state: value === null || !hasThreshold ? 'info' : outside ? 'warn' : 'ok',
    stateText: value === null ? '等待数据' : !hasThreshold ? '阈值未配置' : outside ? '超出阈值' : '阈值内',
  }
}))

onMounted(async () => {
  try { params.value = (await listParams()).data || [] }
  catch (error) { paramError.value = error.message || '监测阈值读取失败' }
})
</script>

<style scoped>
.data-error { margin: 10px 0 0; color: #bd5b52; font-size: 11px; }
.data-boundary p { margin: 0; color: #71899b; font-size: 12px; line-height: 1.7; }
</style>
