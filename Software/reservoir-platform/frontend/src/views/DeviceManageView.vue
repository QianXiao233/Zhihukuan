<template>
  <ViewShell title="设备管理" :tag="`${filteredDevices.length} 台设备 · ${currentDamName}`" :icon="ToolOutlined">
    <section class="view-card manage-panel">
      <div class="manage-toolbar">
        <div><h2 class="view-card__title"><ToolOutlined /> 设备台账</h2><p class="manage-subtitle">管理闸门、传感器和通信设备的基础信息与启用状态。</p></div>
        <div class="manage-actions"><input v-model.trim="query" class="manage-input search-input" placeholder="搜索名称、编码或位置" /><button v-if="canEdit" class="primary-btn" type="button" @click="openCreate">新增设备</button></div>
      </div>
      <div v-if="error" class="manage-error">{{ error }}</div>
      <div v-if="loading" class="manage-empty">正在读取设备台账…</div>
      <div v-else class="table-wrap">
        <table class="manage-table"><thead><tr><th>设备名称</th><th>所属水库</th><th>设备编码</th><th>类型</th><th>安装位置</th><th>协议</th><th>状态</th><th></th></tr></thead>
          <tbody><tr v-for="item in filteredDevices" :key="item.deviceId"><td><strong>{{ item.deviceName || '未命名设备' }}</strong><small>{{ item.manufacturer || '—' }} {{ item.model || '' }}</small></td><td>{{ damName(item.damId) }}</td><td>{{ item.deviceCode || '—' }}</td><td>{{ item.deviceType || '—' }}</td><td>{{ item.installPosition || '—' }}</td><td>{{ item.protocol || '—' }}</td><td><span class="status-dot" :class="item.status === 1 ? 'is-on' : 'is-off'"></span>{{ item.status === 1 ? '启用' : '停用' }}</td><td class="row-actions"><button v-if="canEdit" type="button" @click="openEdit(item)">编辑</button><button v-if="canEdit" type="button" class="danger-link" @click="remove(item)">删除</button></td></tr><tr v-if="!filteredDevices.length"><td colspan="8" class="manage-empty">没有匹配的设备</td></tr></tbody>
        </table>
      </div>
    </section>
        <div v-if="editing" class="modal-backdrop" @click.self="editing = null"><form class="manage-modal" @submit.prevent="save"><div class="modal-head"><div><h2>{{ editing.deviceId ? '编辑设备' : '新增设备' }}</h2><p>基础资料保存后会同步到 MySQL。</p></div><button type="button" class="close-btn" @click="editing = null">×</button></div><div class="form-grid"><label>所属水库<select v-model.number="editing.damId" required><option :value="null" disabled>请选择水库</option><option v-for="dam in dams" :key="dam.damId" :value="dam.damId">{{ dam.damName || `水库 #${dam.damId}` }}</option></select></label><label>设备名称<input v-model.trim="editing.deviceName" required /></label><label>设备编码<input v-model.trim="editing.deviceCode" /></label><label>设备类型<select v-model="editing.deviceType"><option value="闸门">闸门</option><option value="水位传感器">水位传感器</option><option value="水质传感器">水质传感器</option><option value="摄像机">摄像机</option><option value="无人艇">无人艇</option><option value="其他">其他</option></select></label><label>通信协议<input v-model.trim="editing.protocol" placeholder="MQTT / Modbus / WebRTC" /></label><label>安装位置<input v-model.trim="editing.installPosition" /></label><label>厂家/品牌<input v-model.trim="editing.manufacturer" /></label><label>型号<input v-model.trim="editing.model" /></label><label>状态<select v-model.number="editing.status"><option :value="1">启用</option><option :value="0">停用</option></select></label><label class="span-2">备注<textarea v-model.trim="editing.remark" rows="3"></textarea></label></div><div class="modal-foot"><button type="button" class="plain-btn" @click="editing = null">取消</button><button class="primary-btn" type="submit" :disabled="saving || !dams.length">{{ saving ? '保存中…' : (dams.length ? '保存设备' : '请先建立水库') }}</button></div></form></div>
  </ViewShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ToolOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
const accountLevel = Number(localStorage.getItem('level') ?? 1)
const canEdit = accountLevel === 0 || accountLevel >= 2
import { addDevice, deleteDevice, listDevices, updateDevice } from '../api/manageApi.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'

const devices = ref([]); const query = ref(''); const loading = ref(true); const saving = ref(false); const error = ref(''); const editing = ref(null)
const { dams, selectedDamId, currentDamName, loadDams } = useCurrentDam()
const filteredDevices = computed(() => devices.value.filter((item) => String(item.damId) === String(selectedDamId.value) && `${item.deviceName || ''} ${item.deviceCode || ''} ${item.installPosition || ''}`.toLowerCase().includes(query.value.toLowerCase())))
const blank = () => ({ damId: Number(selectedDamId.value) || dams.value[0]?.damId || null, deviceName: '', deviceCode: '', deviceType: '闸门', manufacturer: '', model: '', protocol: 'MQTT', installPosition: '', status: 1, remark: '' })
function damName(damId) { return dams.value.find((dam) => dam.damId === damId)?.damName || (damId ? `水库 #${damId}` : '未关联') }
async function load() { loading.value = true; error.value = ''; try { const [deviceResult] = await Promise.all([listDevices(), loadDams()]); devices.value = deviceResult.data || [] } catch (e) { error.value = e.message } finally { loading.value = false } }
function openCreate() { editing.value = blank() }
function openEdit(item) { editing.value = { ...item } }
async function save() { saving.value = true; error.value = ''; try { if (editing.value.deviceId) await updateDevice(editing.value); else await addDevice(editing.value); editing.value = null; await load() } catch (e) { error.value = e.message } finally { saving.value = false } }
async function remove(item) { if (!window.confirm(`确定删除“${item.deviceName}”吗？`)) return; try { await deleteDevice(item.deviceId); await load() } catch (e) { error.value = e.message } }
onMounted(load)
</script>

<style scoped>
.manage-panel{min-height:100%}.manage-toolbar{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:18px}.manage-subtitle{margin:-8px 0 0;color:#7890a4;font-size:11px}.manage-actions{display:flex;gap:8px;align-items:center}.manage-input,.manage-modal input,.manage-modal select,.manage-modal textarea{border:1px solid #dce8f0;border-radius:8px;background:#fbfdfe;color:#284967;font:inherit;font-size:12px;outline:none}.manage-input{height:34px;padding:0 11px}.search-input{width:210px}.primary-btn,.plain-btn{height:34px;padding:0 14px;border:0;border-radius:8px;font-size:12px;cursor:pointer}.primary-btn{background:#1679d1;color:white;box-shadow:0 6px 15px rgba(22,121,209,.2)}.plain-btn{border:1px solid #d8e5ee;background:#fff;color:#557188}.manage-error{padding:10px 12px;border-radius:8px;background:#fff2f1;color:#b64c4a;font-size:12px;margin-bottom:12px}.table-wrap{overflow:auto}.manage-table{width:100%;border-collapse:collapse;color:#557188;font-size:11px}.manage-table th{padding:11px 10px;color:#8198aa;background:#f5f9fb;font-weight:600;text-align:left;white-space:nowrap}.manage-table td{padding:12px 10px;border-bottom:1px solid #edf2f5;white-space:nowrap}.manage-table td:first-child{min-width:150px}.manage-table strong,.manage-table small{display:block}.manage-table strong{color:#294b66;font-size:12px}.manage-table small{margin-top:2px;color:#9aacb9;font-size:10px}.status-dot{display:inline-block;width:7px;height:7px;margin-right:5px;border-radius:50%;background:#b5c2cc}.status-dot.is-on{background:#24bd8d;box-shadow:0 0 0 3px #e6f8f2}.row-actions{display:flex;gap:10px}.row-actions button{border:0;background:none;color:#227ac2;font-size:11px;cursor:pointer}.row-actions .danger-link{color:#d06462}.manage-empty{text-align:center;color:#91a4b2;padding:28px!important}.modal-backdrop{position:fixed;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(9,35,58,.4)}.manage-modal{width:min(620px,100%);padding:22px;border-radius:15px;background:#fff;box-shadow:0 20px 60px rgba(13,53,82,.25)}.modal-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px}.modal-head h2{margin:0;color:#173955;font-size:18px}.modal-head p{margin:4px 0 0;color:#8298a9;font-size:11px}.close-btn{border:0;background:none;color:#8197a7;font-size:24px;cursor:pointer}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.form-grid label{display:flex;flex-direction:column;gap:5px;color:#617b90;font-size:11px}.form-grid input,.form-grid select{height:35px;padding:0 9px}.form-grid textarea{padding:8px;resize:vertical}.span-2{grid-column:span 2}.modal-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}@media(max-width:700px){.manage-toolbar{flex-direction:column}.manage-actions{width:100%}.search-input{flex:1;width:auto}.form-grid{grid-template-columns:1fr}.span-2{grid-column:auto}}
</style>
