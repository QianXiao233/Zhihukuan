<template>
  <ViewShell title="库区档案" :tag="`${dams.length} 个管理对象`" :icon="BankOutlined">
    <section class="view-card archive-panel">
      <div class="manage-toolbar"><div><h2 class="view-card__title"><BankOutlined /> 水库基础信息</h2><p class="manage-subtitle">维护水库、河流、位置和调度控制水位等基础档案。</p></div><button v-if="canEdit" class="primary-btn" type="button" @click="openCreate">新增水库</button></div>
      <div v-if="error" class="manage-error">{{ error }}</div>
      <div class="archive-grid"><article v-for="dam in dams" :key="dam.damId" class="archive-card"><div class="archive-card__head"><div><strong>{{ dam.damName || '未命名水库' }}</strong><small>{{ dam.damType || '未分类' }} · {{ dam.riverName || '河流未填写' }}</small></div><span :class="dam.status === 1 ? 'is-active' : 'is-disabled'">{{ dam.status === 1 ? '启用' : '停用' }}</span></div><div class="archive-location"><EnvironmentOutlined /> {{ dam.location || '位置未填写' }}</div><div class="level-row"><div><small>设计</small><b>{{ show(dam.designWaterLevel) }} m</b></div><div><small>汛限</small><b>{{ show(dam.floodWaterLevel) }} m</b></div><div><small>死水位</small><b>{{ show(dam.dieWaterLevel) }} m</b></div></div><div class="archive-card__foot"><span>建成年份：{{ dam.buildYear || '—' }}</span><div><button v-if="canEdit" type="button" @click="openEdit(dam)">编辑</button><button v-if="canEdit" type="button" class="danger-link" @click="remove(dam)">删除</button></div></div></article><div v-if="!dams.length" class="manage-empty">暂无水库档案</div></div>
    </section>
    <div v-if="editing" class="modal-backdrop" @click.self="closeEditor"><form class="manage-modal" @submit.prevent="save"><div class="modal-head"><div><h2>{{ editing.damId ? '编辑水库档案' : '新增水库档案' }}</h2><p>这些信息会用于平台顶部管理对象和调度页面展示。</p></div><button type="button" class="close-btn" @click="closeEditor">×</button></div><div v-if="formError" class="manage-error">{{ formError }}</div><div class="form-grid"><label>水库名称<input v-model.trim="editing.damName" required /></label><label>水库类型<input v-model.trim="editing.damType" placeholder="中型 / 小型" /></label><label>所属河流<input v-model.trim="editing.riverName" /></label><label>所在位置<input v-model.trim="editing.location" /></label><label>设计水位（m）<input v-model="editing.designWaterLevel" type="number" min="0" step="0.01" /></label><label>汛限水位（m）<input v-model="editing.floodWaterLevel" type="number" min="0" step="0.01" /></label><label>死水位（m）<input v-model="editing.dieWaterLevel" type="number" min="0" step="0.01" /></label><label>坝高（m）<input v-model="editing.damHeight" type="number" min="0" step="0.01" /></label><label>总库容（万 m³）<input v-model="editing.damStorage" type="number" min="0" step="0.01" placeholder="例如 12000" /></label><label>控制面积（km²）<input v-model="editing.controlArea" type="number" min="0" step="0.01" /></label><label>建成年份<input v-model.trim="editing.buildYear" /></label><label>状态<select v-model.number="editing.status"><option :value="1">启用</option><option :value="0">停用</option></select></label><label class="span-2">备注<textarea v-model.trim="editing.remark" rows="3"></textarea></label></div><div class="modal-foot"><button type="button" class="plain-btn" :disabled="saving" @click="closeEditor">取消</button><button class="primary-btn" type="submit" :disabled="saving">{{ saving ? '保存中…' : '保存档案' }}</button></div></form></div>
  </ViewShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { BankOutlined, EnvironmentOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { validateToken } from '../api/auth.js'
import { addDam, deleteDam, updateDam } from '../api/manageApi.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'
const accountLevel = ref(Number(localStorage.getItem('level') ?? 1))
const canEdit = computed(() => accountLevel.value === 0 || accountLevel.value >= 3)
const { dams, loadDams } = useCurrentDam()
const editing = ref(null); const error = ref(''); const formError = ref(''); const saving = ref(false)
const blank = () => ({ damName: '', damType: '水库', riverName: '', location: '', designWaterLevel: '', floodWaterLevel: '', dieWaterLevel: '', damHeight: '', damStorage: '', controlArea: '', buildYear: '', status: 1, remark: '' })
const show = (value) => value === null || value === undefined || value === '' ? '—' : value
async function load() { error.value = ''; try { await loadDams(true) } catch (e) { error.value = e.message } }
async function refreshPermission() {
  try {
    const identity = await validateToken(localStorage.getItem('token'))
    if (identity.success && identity.level !== undefined) {
      accountLevel.value = Number(identity.level)
      localStorage.setItem('level', String(identity.level))
    }
  } catch { /* 权限校验失败时保留当前缓存；接口仍会在服务端校验身份 */ }
}
function openCreate() { formError.value = ''; editing.value = blank() }
function openEdit(dam) { formError.value = ''; editing.value = { ...dam } }
function closeEditor() { if (!saving.value) editing.value = null }
async function save() {
  saving.value = true; formError.value = ''; error.value = ''
  try {
    if (editing.value.damId) await updateDam(editing.value); else await addDam(editing.value)
    editing.value = null
    await load()
  } catch (e) { formError.value = e.message || '保存失败，请重试' }
  finally { saving.value = false }
}
async function remove(dam) { if (!window.confirm(`确定删除“${dam.damName}”吗？`)) return; try { await deleteDam(dam.damId); await load() } catch (e) { error.value = e.message } }
onMounted(() => { void load(); void refreshPermission() })
</script>

<style scoped>
.archive-panel{min-height:100%}.manage-toolbar{display:flex;justify-content:space-between;align-items:flex-start;gap:18px;margin-bottom:18px}.manage-subtitle{margin:-8px 0 0;color:#7890a4;font-size:11px}.primary-btn,.plain-btn{height:34px;padding:0 14px;border:0;border-radius:8px;font-size:12px;cursor:pointer}.primary-btn{background:#1679d1;color:#fff;box-shadow:0 6px 15px rgba(22,121,209,.18)}.plain-btn{border:1px solid #d8e5ee;background:#fff;color:#557188}.manage-error{margin-bottom:12px;padding:10px 12px;border-radius:8px;background:#fff2f1;color:#b64c4a;font-size:12px}.archive-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.archive-card{padding:17px;border:1px solid #e1ecf3;border-radius:12px;background:#fbfdfe}.archive-card__head{display:flex;justify-content:space-between;gap:12px}.archive-card__head strong,.archive-card__head small{display:block}.archive-card__head strong{color:#294b66;font-size:15px}.archive-card__head small{margin-top:4px;color:#8da1b0;font-size:10px}.archive-card__head span{height:22px;padding:4px 8px;border-radius:6px;font-size:10px}.is-active{background:#e8faf3;color:#168b69}.is-disabled{background:#f1f4f6;color:#8498a6}.archive-location{display:flex;align-items:center;gap:5px;margin:15px 0 12px;color:#6d879b;font-size:11px}.archive-location :deep(svg){color:#4b9ed2}.level-row{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;padding:12px 0;border-top:1px solid #edf2f5;border-bottom:1px solid #edf2f5}.level-row small,.level-row b{display:block}.level-row small{color:#96a8b4;font-size:10px}.level-row b{margin-top:3px;color:#315d7d;font-size:14px}.archive-card__foot{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:13px;color:#91a1ad;font-size:10px}.archive-card__foot button{border:0;background:none;color:#247cc2;font-size:11px;cursor:pointer}.archive-card__foot .danger-link{margin-left:10px;color:#d06462}.manage-empty{grid-column:1/-1;padding:30px;text-align:center;color:#91a4b2}.modal-backdrop{position:fixed;inset:0;z-index:20;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(9,35,58,.4)}.manage-modal{width:min(650px,100%);max-height:90vh;overflow:auto;padding:22px;border-radius:15px;background:#fff;box-shadow:0 20px 60px rgba(13,53,82,.25)}.modal-head{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:18px}.modal-head h2{margin:0;color:#173955;font-size:18px}.modal-head p{margin:4px 0 0;color:#8298a9;font-size:11px}.close-btn{border:0;background:none;color:#8197a7;font-size:24px;cursor:pointer}.form-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:13px}.form-grid label{display:flex;flex-direction:column;gap:5px;color:#617b90;font-size:11px}.form-grid input,.form-grid select,.form-grid textarea{border:1px solid #dce8f0;border-radius:8px;background:#fbfdfe;color:#284967;font:inherit;font-size:12px;outline:none}.form-grid input,.form-grid select{height:35px;padding:0 9px}.form-grid textarea{padding:8px;resize:vertical}.span-2{grid-column:span 2}.modal-foot{display:flex;justify-content:flex-end;gap:8px;margin-top:20px}@media(max-width:700px){.manage-toolbar{flex-direction:column}.archive-grid,.form-grid{grid-template-columns:1fr}.span-2{grid-column:auto}}
</style>
