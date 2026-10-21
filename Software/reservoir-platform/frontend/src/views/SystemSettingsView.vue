<template>
  <ViewShell title="系统设置" tag="平台配置" :icon="SettingOutlined">
    <p v-if="passwordError" class="password-error" role="alert">{{ passwordError }}</p><div class="settings-grid">
      <section class="view-card settings-card"><h2 class="view-card__title"><UserOutlined /> 当前账号</h2><div class="account-block"><span class="account-avatar">管</span><div><strong>{{ username }}</strong><small>{{ Number(level) === 0 || Number(level) >= 3 ? '系统管理员' : Number(level) === 2 ? '运维人员' : '值守人员' }}</small></div></div><div class="settings-row"><span>登录状态</span><b class="connected">已登录</b></div><div class="settings-row"><span>权限等级</span><b>Level {{ level }}</b></div></section>
      <section class="view-card settings-card"><h2 class="view-card__title"><BgColorsOutlined /> 显示偏好</h2><label class="setting-control"><span><strong>紧凑信息密度</strong><small>减少表格和卡片间距，适合大屏值守</small></span><input v-model="preferences.compact" type="checkbox" @change="savePreferences" /></label><label class="setting-control"><span><strong>自动刷新通知</strong><small>每 30 秒读取一次未读消息数量</small></span><input v-model="preferences.autoRefresh" type="checkbox" @change="savePreferences" /></label><label class="setting-control"><span><strong>界面字号</strong><small>调整平台业务页面的基础字号</small></span><select v-model="preferences.fontSize" @change="savePreferences"><option value="small">小</option><option value="normal">标准</option><option value="large">大</option></select></label><span v-if="saved" class="saved-tip">偏好已保存</span></section>
      <section class="view-card settings-card"><h2 class="view-card__title"><CloudServerOutlined /> 数据接入</h2><div class="connection-item"><span class="connection-dot"></span><div><strong>MQTT 水情接入</strong><small>前端直连 RTU，负责传感器数据和闸门控制</small></div><b>参数已配置</b></div><div class="connection-detail"><span>Broker</span><code>{{ broker }}</code></div><div class="connection-detail"><span>主题</span><code>rtu/status</code></div><div class="connection-item"><span class="connection-dot"></span><div><strong>船载视角 Janus</strong><small>无人艇视频流，Stream ID {{ streamId }}</small></div><b>参数已配置</b></div><div class="connection-detail"><span>Gateway</span><code>{{ janusUrl }}</code></div></section>
      <section v-if="canManagePush" class="view-card settings-card push-card"><h2 class="view-card__title"><NotificationOutlined /> 推送与告警</h2><p class="push-note">读数超出阈值、登录异常时通过推送服务发出提醒；同一指标在冷却时间内只推一次，避免连续轰炸。</p><form class="push-form" @submit.prevent="savePush"><label>推送 Token<input v-model="pushForm.token" type="password" autocomplete="new-password" :placeholder="pushConfig?.tokenConfigured ? `当前 ${pushConfig.tokenMasked}（留空不修改）` : '粘贴推送服务提供的 token'" /></label><div class="push-row"><label>冷却时间（分钟）<input v-model.number="pushForm.cooldownMinutes" type="number" min="0" max="1440" /></label><label class="push-toggle"><span>启用推送</span><input v-model="pushForm.enabled" type="checkbox" /></label></div><div class="push-actions"><button class="push-primary" type="submit" :disabled="pushSaving">{{ pushSaving ? '保存中…' : '保存配置' }}</button><button class="push-plain" type="button" :disabled="pushTesting" @click="sendTestPush">{{ pushTesting ? '发送中…' : '发送测试消息' }}</button><button class="push-plain" type="button" @click="clearPushToken">清除 Token</button></div><p v-if="pushMessage" class="push-tip" :class="{ bad: pushError }">{{ pushMessage }}</p><div v-if="pushConfig" class="push-meta"><span>状态 <b :class="pushConfig.enabled ? 'on' : 'off'">{{ pushConfig.enabled ? '已启用' : '已停用' }}</b></span><span>Token <b :class="pushConfig.tokenConfigured ? 'on' : 'off'">{{ pushConfig.tokenConfigured ? pushConfig.tokenMasked : '未配置' }}</b></span><span>来源 {{ pushConfig.tokenSource === 'database' ? '管理页' : '配置文件' }}</span></div></form></section>
      <section class="view-card settings-card"><h2 class="view-card__title"><InfoCircleOutlined /> 平台信息</h2><div class="settings-row"><span>平台名称</span><b>智御安澜水库数字化运营平台</b></div><div class="settings-row"><span>当前水库</span><b>{{ currentDamName }}</b></div><div class="settings-row"><span>前端版本</span><b>Vue 3 · Vite</b></div><div class="settings-row"><span>后端服务</span><b>Spring Boot · MySQL + MongoDB</b></div><p class="settings-note">台账、阈值、通知存在 MySQL；水情读数与告警记录存在 MongoDB。</p></section>
      <section class="view-card settings-card"><h2 class="view-card__title"><UserOutlined /> 修改登录密码</h2><form class="password-form" @submit.prevent="updatePassword"><label>原密码<input v-model="password.old" type="password" required autocomplete="current-password" /></label><label>新密码<input v-model="password.next" type="password" minlength="6" required autocomplete="new-password" /></label><label>确认新密码<input v-model="password.confirm" type="password" minlength="6" required autocomplete="new-password" /></label><button :disabled="passwordSaving">{{ passwordSaving ? '保存中…' : '修改密码并重新登录' }}</button></form></section>
    </div>
  </ViewShell>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { BgColorsOutlined, CloudServerOutlined, InfoCircleOutlined, NotificationOutlined, SettingOutlined, UserOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import { useRouter } from 'vue-router'
import { changePassword, getPushConfig, savePushConfig, testPush } from '../api/manageApi.js'
import { useCurrentDam } from '../composables/useCurrentDam.js'
import { clearAuth } from '../api/auth.js'
import { mqttUrl } from '../utils/mqttService.js'
import { JANUS_STREAM_ID as streamId, JANUS_URL as janusUrl } from '../utils/boatConfig.js'
const broker = mqttUrl()
const router = useRouter()
const password = reactive({ old: '', next: '', confirm: '' })
const passwordError = ref(''), passwordSaving = ref(false)
async function updatePassword() { passwordError.value = ''; if(password.next !== password.confirm){passwordError.value='两次输入的新密码不一致';return} passwordSaving.value=true; try { await changePassword(password.old, password.next); clearAuth(); await router.replace({name:'login'}) } catch(e){passwordError.value=e.message} finally{passwordSaving.value=false} }
const username = localStorage.getItem('username') || '管理员'
const level = localStorage.getItem('level') || '1'
const saved = ref(false)
const preferences = reactive({ compact: localStorage.getItem('platform.compact') === 'true', autoRefresh: localStorage.getItem('platform.autoRefresh') !== 'false', fontSize: localStorage.getItem('platform.fontSize') || 'normal' })
const { currentDamName } = useCurrentDam()
function savePreferences() { localStorage.setItem('platform.compact', String(preferences.compact)); localStorage.setItem('platform.autoRefresh', String(preferences.autoRefresh)); localStorage.setItem('platform.fontSize', preferences.fontSize); window.dispatchEvent(new Event('platform-preferences')); saved.value = true; window.setTimeout(() => { saved.value = false }, 1800) }

// ─────────── 推送与告警 ───────────
const canManagePush = Number(level) === 0 || Number(level) >= 3
const pushConfig = ref(null)
const pushForm = reactive({ token: '', cooldownMinutes: 10, enabled: true })
const pushMessage = ref('')
const pushError = ref(false)
const pushSaving = ref(false)
const pushTesting = ref(false)

async function loadPush() {
  if (!canManagePush) return
  try {
    const data = (await getPushConfig()).data || {}
    pushConfig.value = data
    pushForm.cooldownMinutes = Number(data.cooldownMinutes ?? 10)
    pushForm.enabled = data.enabled !== false
  } catch (e) {
    pushMessage.value = e.message
    pushError.value = true
  }
}

function applyPushResult(data) {
  pushConfig.value = data
  pushForm.cooldownMinutes = Number(data.cooldownMinutes ?? 10)
  pushForm.enabled = data.enabled !== false
  pushForm.token = ''
}

async function savePush() {
  pushSaving.value = true
  pushMessage.value = ''
  pushError.value = false
  try {
    const data = (await savePushConfig({ token: pushForm.token, enabled: String(pushForm.enabled), cooldown_minutes: pushForm.cooldownMinutes })).data || {}
    applyPushResult(data)
    pushMessage.value = '推送配置已保存'
  } catch (e) {
    pushMessage.value = e.message
    pushError.value = true
  } finally {
    pushSaving.value = false
  }
}

async function sendTestPush() {
  pushTesting.value = true
  pushMessage.value = ''
  pushError.value = false
  try {
    const result = await testPush()
    pushMessage.value = result.message || '测试消息已发送'
  } catch (e) {
    pushMessage.value = e.message
    pushError.value = true
  } finally {
    pushTesting.value = false
  }
}

async function clearPushToken() {
  if (!window.confirm('清除数据库中的推送 token？清除后将回退到配置文件里的兜底 token（一般为空）。')) return
  pushMessage.value = ''
  pushError.value = false
  try {
    const data = (await savePushConfig({ clear_token: 'true' })).data || {}
    applyPushResult(data)
    pushMessage.value = '已清除数据库中的 token'
  } catch (e) {
    pushMessage.value = e.message
    pushError.value = true
  }
}

onMounted(loadPush)
</script>

<style scoped>
.password-form{display:grid;gap:12px}.password-form label{display:grid;gap:5px;color:#617b90;font-size:12px}.password-form input{height:35px;border:1px solid #dce8f0;border-radius:7px;padding:0 9px}.password-form button{height:35px;background:#1679d1;color:#fff;border:0;border-radius:7px;cursor:pointer}.password-error{padding:12px;background:#fff1ef;color:#bd5350;border-radius:7px;font-size:12px}

.view-card{padding:18px;border:1px solid #e2ebf3;border-radius:15px;background:rgba(255,255,255,.93);box-shadow:0 8px 22px rgba(31,80,117,.06)}
.view-card__title{display:flex;align-items:center;gap:8px;margin:0 0 14px;color:#1b3e5c;font-size:14px;font-weight:650}

.settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.settings-card{min-height:220px}.account-block{display:flex;align-items:center;gap:12px;padding:9px 0 16px}.account-avatar{display:flex;align-items:center;justify-content:center;width:42px;height:42px;border-radius:50%;background:linear-gradient(135deg,#55c4ed,#2176d5);color:#fff;font-size:17px}.account-block strong,.account-block small{display:block}.account-block strong{color:#294b66;font-size:15px}.account-block small{margin-top:2px;color:#8ca0ae;font-size:11px}.settings-row{display:flex;justify-content:space-between;gap:14px;padding:11px 0;border-top:1px solid #edf2f5;color:#7890a2;font-size:11px}.settings-row b{color:#315571;font-weight:600;text-align:right}.connected{color:#159774!important}.setting-control{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid #edf2f5;color:#315571;cursor:pointer}.setting-control:last-of-type{border-bottom:0}.setting-control strong,.setting-control small{display:block}.setting-control strong{font-size:12px}.setting-control small{margin-top:3px;color:#8a9daa;font-size:10px}.setting-control input{appearance:none;width:35px;height:20px;border-radius:12px;background:#c6d4dc;cursor:pointer;position:relative;transition:.2s}.setting-control input::after{content:'';position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:#fff;transition:.2s}.setting-control input:checked{background:#2dbb96}.setting-control input:checked::after{left:18px}.setting-control select{height:30px;padding:0 8px;border:1px solid #dce8f0;border-radius:7px;background:#fbfdfe;color:#557188;font-size:11px}.saved-tip{display:block;margin-top:10px;color:#159774;font-size:10px}.connection-item{display:flex;align-items:flex-start;gap:9px;padding:9px 0}.connection-dot{width:8px;height:8px;flex:0 0 8px;margin-top:5px;border-radius:50%;background:#aab9c3}.connection-dot.is-on{background:#29bc91;box-shadow:0 0 0 3px rgba(41,188,145,.14)}.connection-item strong,.connection-item small{display:block}.connection-item strong{color:#315571;font-size:12px}.connection-item small{margin-top:2px;color:#8a9daa;font-size:10px}.connection-item b{margin-left:auto;color:#159774;font-size:10px}.connection-detail{display:flex;justify-content:space-between;gap:10px;padding:5px 0 5px 17px;color:#8a9daa;font-size:10px}.connection-detail code{color:#4d6d86;font-size:10px}.settings-note{margin:6px 0 0;color:#8a9daa;font-size:10px;line-height:1.6}

.push-card{display:flex;flex-direction:column}
.push-note{margin:-4px 0 12px;color:#8a9daa;font-size:10px;line-height:1.6}
.push-form{display:flex;flex-direction:column;gap:11px}
.push-form label{display:grid;gap:5px;color:#617b90;font-size:11px}
.push-form input[type='password'],.push-form input[type='number']{height:34px;border:1px solid #dce8f0;border-radius:7px;padding:0 9px;color:#355571;font-size:11px;background:#fff}
.push-row{display:flex;align-items:flex-end;gap:16px;flex-wrap:wrap}
.push-row label{flex:0 0 150px}
.push-toggle{display:flex!important;flex-direction:row!important;align-items:center;gap:8px;padding-bottom:8px;color:#315571;font-size:11px;cursor:pointer}
.push-toggle input{appearance:none;width:35px;height:20px;border-radius:12px;background:#c6d4dc;cursor:pointer;position:relative;transition:.2s}
.push-toggle input::after{content:'';position:absolute;top:3px;left:3px;width:14px;height:14px;border-radius:50%;background:#fff;transition:.2s}
.push-toggle input:checked{background:#2dbb96}
.push-toggle input:checked::after{left:18px}
.push-actions{display:flex;gap:8px;flex-wrap:wrap}
.push-primary,.push-plain{height:32px;padding:0 13px;border-radius:7px;font-size:11px;cursor:pointer}
.push-primary{border:0;background:#1679d1;color:#fff}
.push-plain{border:1px solid #d8e5ee;background:#fff;color:#557188}
.push-primary:disabled,.push-plain:disabled{opacity:.55;cursor:not-allowed}
.push-tip{margin:0;padding:8px 10px;border-radius:7px;background:#eefaf5;color:#168b69;font-size:10px}
.push-tip.bad{background:#fff2f1;color:#b64c4a}
.push-meta{display:flex;flex-wrap:wrap;gap:14px;padding-top:9px;border-top:1px dashed #e6eef4;color:#8a9daa;font-size:10px}
.push-meta b{font-weight:600}
.push-meta b.on{color:#168b69}
.push-meta b.off{color:#b57322}
</style>
