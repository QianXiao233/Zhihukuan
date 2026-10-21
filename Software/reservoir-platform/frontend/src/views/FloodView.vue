<template>
  <ViewShell title="防汛调度" :tag="mqttConnected ? '闸门控制 · MQTT 已连接' : '闸门控制 · 等待 MQTT'" :icon="ThunderboltOutlined">

    <section class="view-card">
          <p class="gate-connection"><i :class="{ online: mqttConnected }"></i>{{ !mqttConnected ? 'MQTT 未连接，无法下发控制指令' : hasGateStatus ? '已收到闸门状态，数据来自 rtu/status' : 'MQTT 已连接，等待 rtu/status 闸门数据' }}<span v-if="controlNotice" class="control-notice" :class="{ error: controlNotice.error }">{{ controlNotice.text }}</span></p>
      <div class="gate-control-grid">
        <div v-for="(state, index) in gates" :key="index" class="gate-control-item">
          <div><strong>{{ index + 1 }}号闸门</strong><span :class="!hasGateStatus ? 'closed' : state === 1 ? 'open' : 'closed'">{{ !hasGateStatus ? '等待数据' : state === 1 ? '开启' : '关闭' }}</span></div>
            <button type="button" class="gate-toggle" :class="state === 1 ? 'is-open' : 'is-closed'" :disabled="!mqttConnected || !hasGateStatus" :aria-label="state === 1 ? `关闭${index + 1}号闸门` : `开启${index + 1}号闸门`" @click="requestGate(index + 1)"><span class="gate-toggle__track"><span class="gate-toggle__thumb"></span></span><span class="gate-toggle__label"><b>{{ !hasGateStatus ? '等待状态数据' : state === 1 ? '已开启' : '已关闭' }}</b><small>{{ !hasGateStatus ? '等待 RTU 上报' : state === 1 ? '点击关闭' : '点击开启' }}</small></span><component :is="state === 1 ? ArrowDownOutlined : ArrowUpOutlined" class="gate-toggle__icon" /></button>
        </div>
      </div>
    </section>
  </ViewShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ArrowDownOutlined, ArrowUpOutlined, ThunderboltOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { useReservoirMqtt } from '../composables/useReservoirMqtt.js'

const { mqttConnected, realtime, gates, toggleGate } = useReservoirMqtt()
const hasGateStatus = computed(() => Boolean(realtime.value?.relayReported))
const controlNotice = ref(null)

function requestGate(id) {
  if (!hasGateStatus.value) return
  const ok = toggleGate(id)
  controlNotice.value = ok ? { text: `${id}号闸门控制指令已发布`, error: false } : { text: 'MQTT 未连接，指令未发布', error: true }
  window.setTimeout(() => { controlNotice.value = null }, 3200)
}

</script>

<style scoped>
.gate-connection{display:flex;align-items:center;gap:7px;margin:-4px 0 13px;color:#8196a6;font-size:11px}.gate-connection i{width:7px;height:7px;border-radius:50%;background:#c0cbd2}.gate-connection i.online{background:#27c49a}.control-notice{margin-left:auto;color:#1b9e76}.control-notice.error{color:#bd5b45}.gate-control-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.gate-control-item{padding:12px;border:1px solid #e5edf3;border-radius:10px;background:#fbfdfe}.gate-control-item>div{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px}.gate-control-item strong{color:#3c5e76;font-size:11px}.gate-control-item span{font-size:10px}.gate-control-item span.open{color:#188f6e}.gate-control-item span.closed{color:#8195a4}.gate-control-item button{width:100%;height:29px;border:1px solid #cbe0ed;border-radius:7px;background:#eef7fc;color:#2b80b7;font-size:10px;cursor:pointer}.gate-control-item button:disabled{cursor:not-allowed;opacity:.55}@media(max-width:900px){.gate-control-grid{grid-template-columns:repeat(2,1fr)}}
.gate-control-grid{gap:10px}.gate-control-item{padding:13px;border-radius:12px;background:linear-gradient(145deg,#fff 0%,#f8fbfd 100%);box-shadow:0 6px 16px rgba(38,83,116,.045)}.gate-action{display:flex;align-items:center;justify-content:center;gap:6px;width:100%;height:34px;border:1px solid;border-radius:9px;font-size:10px;font-weight:600;letter-spacing:.01em;cursor:pointer;transition:transform .16s ease,box-shadow .16s ease,background .16s ease}.gate-action :deep(svg){font-size:13px}.gate-action__arrow{margin-left:auto;font-size:16px;line-height:1;opacity:.72}.gate-action.is-open{border-color:#b4e5d4;background:linear-gradient(135deg,#effcf7,#dff8ed);color:#138968;box-shadow:0 4px 10px rgba(32,177,133,.12)}.gate-action.is-close{border-color:#c7ddec;background:linear-gradient(135deg,#f2f8fd,#e6f2fb);color:#247bae;box-shadow:0 4px 10px rgba(37,128,177,.1)}.gate-action:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 7px 14px rgba(38,102,142,.15)}.gate-action:active:not(:disabled){transform:translateY(0) scale(.985)}.gate-action:disabled{cursor:not-allowed;filter:grayscale(.45);opacity:.48;box-shadow:none}
.gate-toggle{display:flex;align-items:center;gap:9px;width:100%;min-height:48px;padding:7px 9px;border:1px solid #e0eaf1;border-radius:12px;outline:none;background:#f7fafc;color:#547189;text-align:left;cursor:pointer;transition:border-color .18s ease,background .18s ease,box-shadow .18s ease,transform .18s ease}.gate-toggle:focus-visible{border-color:#64b6e8;box-shadow:0 0 0 3px rgba(56,157,218,.18)}.gate-toggle:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 7px 14px rgba(35,89,122,.1)}.gate-toggle:active:not(:disabled){transform:scale(.985)}.gate-toggle:disabled{cursor:not-allowed;opacity:.5;filter:grayscale(.35)}.gate-toggle__track{position:relative;flex:0 0 40px;width:40px;height:23px;border-radius:99px;background:#d9e5ed;box-shadow:inset 0 1px 3px rgba(21,67,95,.16);transition:background .2s ease}.gate-toggle__thumb{position:absolute;top:3px;left:3px;width:17px;height:17px;border-radius:50%;background:#fff;box-shadow:0 2px 5px rgba(20,64,88,.22);transition:transform .2s ease}.gate-toggle.is-open{border-color:#b7ead8;background:linear-gradient(135deg,#f6fffb,#e8faf3)}.gate-toggle.is-open .gate-toggle__track{background:#2abf92}.gate-toggle.is-open .gate-toggle__thumb{transform:translateX(17px)}.gate-toggle.is-closed:hover:not(:disabled){border-color:#bcd8e9;background:#f1f8fc}.gate-toggle__label{display:flex;flex:1;flex-direction:column;gap:2px;min-width:0}.gate-toggle__label b{color:#355b73;font-size:10px;font-weight:650}.gate-toggle.is-open .gate-toggle__label b{color:#168c6c}.gate-toggle__label small{color:#91a4b2;font-size:9px}.gate-toggle__icon{flex:0 0 auto;color:#8ca5b4;font-size:12px}.gate-toggle.is-open .gate-toggle__icon{color:#24a77f}
</style>

