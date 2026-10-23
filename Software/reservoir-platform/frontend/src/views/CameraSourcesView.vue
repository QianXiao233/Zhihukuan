<template>
  <ViewShell title="画面来源" :tag="`${sources.length} 路来源 · ${enabledCount} 路启用`" :icon="VideoCameraOutlined">
    <div v-if="!canManage" class="cs-denied">
      <SafetyCertificateOutlined />
      <strong>仅系统管理员可配置画面来源</strong>
      <p>当前账号可以查看监控画面，但不能新增或修改视频接入地址。</p>
      <button type="button" @click="go('monitoring-center')">返回监控中心</button>
    </div>

    <template v-else>
      <section class="view-card cs-panel">
        <div class="cs-toolbar">
          <div>
            <h2 class="view-card__title"><VideoCameraOutlined /> 视频接入清单</h2>
            <p class="cs-subtitle">支持 RTSP 摄像机与 WebRTC（WHEP）流。浏览器不能直接播放 RTSP，RTSP 画面由视频网关转封装后接入。</p>
          </div>
          <div class="cs-toolbar__actions">
            <input v-model.trim="query" class="cs-input" placeholder="搜索名称、位置或地址" />
            <button type="button" class="cs-btn cs-btn--plain" @click="go('monitoring-center')">查看视频墙</button>
            <button type="button" class="cs-btn cs-btn--primary" @click="openCreate">新增画面</button>
          </div>
        </div>

        <div class="cs-metrics">
          <div><small>画面总数</small><strong>{{ sources.length }}</strong></div>
          <div><small>已启用</small><strong class="is-on">{{ enabledCount }}</strong></div>
          <div><small>RTSP 接入</small><strong>{{ rtspCount }}</strong></div>
          <div><small>WebRTC 接入</small><strong>{{ webrtcCount }}</strong></div>
        </div>

        <div v-if="error" class="cs-error">{{ error }}</div>
        <div v-if="loading" class="cs-empty">正在读取画面来源…</div>
        <div v-else-if="!filteredSources.length" class="cs-empty">{{ error ? '画面来源读取失败，请检查后端服务后重试。' : sources.length ? '没有匹配的画面来源' : '还没有配置画面。点击右上角「新增画面」开始接入。' }}</div>
        <div v-else class="cs-table-wrap">
          <table class="cs-table">
            <thead>
              <tr><th>画面</th><th>安装位置</th><th>协议</th><th>视频地址</th><th>网关 / 播放标识</th><th>数字孪生</th><th>状态</th><th>排序</th><th></th></tr>
            </thead>
            <tbody>
              <tr v-for="item in filteredSources" :key="item.sourceId">
                <td><strong>{{ item.sourceName }}</strong><small v-if="item.remark">{{ item.remark }}</small></td>
                <td>{{ item.location || '—' }}</td>
                <td><span class="cs-protocol" :class="`is-${item.protocol}`">{{ item.protocol === 'rtsp' ? 'RTSP' : 'WebRTC' }}</span></td>
                <td><code class="cs-url" :title="item.sourceUrl">{{ item.sourceUrl }}</code></td>
                <td>
                  <template v-if="item.protocol === 'rtsp'">
                    <code class="cs-url" :title="`${item.gatewayUrl || '默认网关'} / ${item.streamKey || '未填写'}`">{{ item.streamKey || '未填写播放标识' }}</code>
                    <small>{{ item.gatewayUrl || '使用默认网关' }}</small>
                  </template>
                  <span v-else class="cs-muted">直接 WHEP 播放</span>
                </td>
                <td>
                  <span v-if="item.twinLabel" class="cs-twin">{{ twinLabelText(item.twinLabel) }}</span>
                  <span v-else class="cs-muted">未绑定</span>
                </td>
                <td><span class="cs-status" :class="item.enabled === 0 ? 'is-off' : 'is-on'">{{ item.enabled === 0 ? '停用' : '启用' }}</span></td>
                <td>{{ item.sortOrder ?? 100 }}</td>
                <td class="cs-row-actions">
                  <button type="button" @click="openEdit(item)">编辑</button>
                  <button type="button" class="is-danger" @click="remove(item)">删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <div v-if="editing" class="cs-modal-backdrop" @click.self="editing = null">
        <form class="cs-modal" @submit.prevent="save">
          <header class="cs-modal__head">
            <div>
              <h2>{{ editing.sourceId ? '编辑画面来源' : '新增画面来源' }}</h2>
              <p>一段监控画面对应一条来源记录，保存后立即出现在监控中心视频墙。</p>
            </div>
            <button type="button" class="cs-close" @click="editing = null">×</button>
          </header>

          <div class="cs-form">
            <label>画面名称<input v-model.trim="editing.sourceName" maxlength="100" required placeholder="例如：主坝上游全景" /></label>
            <label>安装位置<input v-model.trim="editing.location" maxlength="255" placeholder="例如：主坝左岸" /></label>

            <div class="cs-span-2 cs-protocol-picker">
              <span>接入协议</span>
              <div>
                <button type="button" :class="{ 'is-active': editing.protocol === 'rtsp' }" @click="editing.protocol = 'rtsp'">
                  <strong>RTSP</strong><small>摄像机原始地址，经网关转 WebRTC 播放</small>
                </button>
                <button type="button" :class="{ 'is-active': editing.protocol === 'webrtc' }" @click="editing.protocol = 'webrtc'">
                  <strong>WebRTC</strong><small>直接填写 WHEP 播放地址，浏览器原生播放</small>
                </button>
              </div>
            </div>

            <label v-if="editing.protocol === 'rtsp'" class="cs-span-2">
              摄像机 RTSP 地址
              <input v-model.trim="editing.sourceUrl" required placeholder="rtsp://admin:密码@192.168.2.50:554/Streaming/Channels/101" />
              <small>摄像机或 NVR 提供的 RTSP 主/子码流地址。</small>
            </label>
            <label v-else class="cs-span-2">
              WebRTC 播放地址（WHEP）
              <input v-model.trim="editing.sourceUrl" required placeholder="http://192.168.2.7:8889/topcam/whep" />
              <small>MediaMTX 的网页地址可只填到流名称（如 http://192.168.2.7:8889/topcam），播放时会自动补 /whep。</small>
            </label>

            <template v-if="editing.protocol === 'rtsp'">
              <label>
                网关地址
                <input v-model.trim="editing.gatewayUrl" placeholder="http://192.168.2.7:8889" />
                <small>MediaMTX / go2rtc 的 WebRTC 网关地址，留空使用默认值。</small>
              </label>
              <label>
                网关播放标识
                <input v-model.trim="editing.streamKey" placeholder="例如：topcam" />
                <small>该路 RTSP 在网关上对应的路径名称，最终播放 <code>网关地址/播放标识/whep</code>。</small>
              </label>
            </template>

            <label class="cs-span-2">
              覆盖播放地址（可选）
              <input v-model.trim="editing.playUrl" placeholder="https://gateway.example.com/stream/abc/whep" />
              <small>填写后将忽略上面的自动拼接逻辑，直接使用该 WHEP 地址。</small>
            </label>

            <label>
              排序
              <input v-model.number="editing.sortOrder" type="number" min="0" max="9999" />
              <small>数字越小越靠前。</small>
            </label>
            <label>
              状态
              <select v-model.number="editing.enabled">
                <option :value="1">启用</option>
                <option :value="0">停用</option>
              </select>
            </label>

            <label>
              数字孪生标签
              <select v-model="editing.twinLabel">
                <option value="">不绑定</option>
                <option value="drowning">溺水监测点</option>
                <option value="boat">无人艇（预留）</option>
              </select>
              <small>绑定后，对应标签的视频弹窗会播放这一路画面；一个标签只保留一路。</small>
            </label>

            <label class="cs-span-2">备注<textarea v-model.trim="editing.remark" rows="3" maxlength="500" placeholder="可选，例如设备型号、维护说明"></textarea></label>
          </div>

          <p v-if="formError" class="cs-form-error">{{ formError }}</p>

          <footer class="cs-modal__foot">
            <span class="cs-note"><InfoCircleOutlined /> RTSP 无法被浏览器直接播放，请先确认视频网关已拉取该路码流。</span>
            <div>
              <button type="button" class="cs-btn cs-btn--plain" @click="editing = null">取消</button>
              <button type="submit" class="cs-btn cs-btn--primary" :disabled="saving">{{ saving ? '保存中…' : '保存画面' }}</button>
            </div>
          </footer>
        </form>
      </div>
    </template>
  </ViewShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  InfoCircleOutlined,
  SafetyCertificateOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import {
  addCameraSource,
  deleteCameraSource,
  listCameraSources,
  updateCameraSource,
} from '../api/manageApi.js'
import { DEFAULT_VIDEO_GATEWAY, saveDefaultGateway } from '../utils/videoSource.js'

const router = useRouter()
const accountLevel = Number(localStorage.getItem('level') ?? 1)
const canManage = accountLevel === 0 || accountLevel >= 3

const sources = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const formError = ref('')
const query = ref('')
const editing = ref(null)

const enabledCount = computed(() => sources.value.filter((item) => item.enabled !== 0).length)
const rtspCount = computed(() => sources.value.filter((item) => item.protocol === 'rtsp').length)
const webrtcCount = computed(() => sources.value.filter((item) => item.protocol === 'webrtc').length)
const filteredSources = computed(() => {
  const keyword = query.value.toLowerCase()
  if (!keyword) return sources.value
  return sources.value.filter((item) => `${item.sourceName || ''} ${item.location || ''} ${item.sourceUrl || ''}`.toLowerCase().includes(keyword))
})

function blank() {
  return {
    sourceId: null,
    sourceName: '',
    location: '',
    protocol: 'webrtc',
    sourceUrl: '',
    playUrl: '',
    gatewayUrl: localStorage.getItem('platform.videoGateway') || DEFAULT_VIDEO_GATEWAY,
    streamKey: '',
    enabled: 1,
    sortOrder: 100,
    twinLabel: '',
    remark: '',
  }
}

function go(name) {
  void router.push({ name })
}

function twinLabelText(value) {
  return value === 'drowning' ? '溺水监测点' : value === 'boat' ? '无人艇' : value
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const result = await listCameraSources()
    sources.value = result.data || []
  } catch (e) {
    error.value = e.message || '画面来源读取失败'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  formError.value = ''
  editing.value = blank()
}

function openEdit(item) {
  formError.value = ''
  editing.value = { ...blank(), ...item, playUrl: item.playUrl || '', gatewayUrl: item.gatewayUrl || '', streamKey: item.streamKey || '', remark: item.remark || '', location: item.location || '' }
}

async function save() {
  if (!editing.value || saving.value) return
  saving.value = true
  formError.value = ''
  try {
    const payload = { ...editing.value }
    if (payload.sourceId) await updateCameraSource(payload)
    else await addCameraSource(payload)
    if (payload.gatewayUrl) saveDefaultGateway(payload.gatewayUrl)
    editing.value = null
    await load()
  } catch (e) {
    formError.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function remove(item) {
  if (!window.confirm(`确定删除「${item.sourceName}」吗？删除后视频墙将不再显示这一路画面。`)) return
  try {
    await deleteCameraSource(item.sourceId)
    await load()
  } catch (e) {
    error.value = e.message || '删除失败'
  }
}

onMounted(() => {
  if (canManage) void load()
})
</script>

<style scoped>
.cs-panel { min-height: 100%; }
.cs-toolbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 15px; }
.cs-subtitle { margin: -7px 0 0; color: #7d93a6; font-size: 10px; line-height: 1.7; }
.cs-toolbar__actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.cs-input { width: 210px; height: 34px; padding: 0 11px; border: 1px solid #dce8f0; border-radius: 8px; background: #fbfdfe; color: #284967; font: inherit; font-size: 11px; outline: none; }
.cs-input:focus { border-color: #8fc4e8; }
.cs-btn { display: inline-flex; align-items: center; justify-content: center; gap: 5px; height: 34px; padding: 0 13px; border-radius: 8px; font: inherit; font-size: 11px; cursor: pointer; white-space: nowrap; }
.cs-btn--plain { border: 1px solid #d8e5ee; background: #fff; color: #557188; }
.cs-btn--plain:hover { border-color: #9fcde8; color: #1d79bd; }
.cs-btn--primary { border: 0; background: #1679d1; color: #fff; box-shadow: 0 6px 15px rgba(22,121,209,.2); }
.cs-btn--primary:hover:not(:disabled) { background: #0f6dc3; }
.cs-btn:disabled { opacity: .6; cursor: not-allowed; }

.cs-metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 15px; }
.cs-metrics > div { padding: 10px 12px; border: 1px solid #eaf0f4; border-radius: 9px; background: #fbfdfe; }
.cs-metrics small { display: block; color: #8fa2b2; font-size: 9px; }
.cs-metrics strong { display: block; margin-top: 4px; color: #315a77; font-size: 20px; line-height: 1; }
.cs-metrics strong.is-on { color: #1a9d76; }

.cs-error { margin-bottom: 12px; padding: 9px 11px; border-radius: 8px; background: #fff2f1; color: #b64c4a; font-size: 11px; }
.cs-empty { display: flex; align-items: center; justify-content: center; min-height: 240px; color: #91a4b2; font-size: 11px; text-align: center; }
.cs-table-wrap { overflow: auto; }
.cs-table { width: 100%; border-collapse: collapse; color: #557188; font-size: 11px; }
.cs-table th { padding: 10px 9px; color: #8198aa; background: #f5f9fb; font-weight: 600; text-align: left; white-space: nowrap; }
.cs-table td { padding: 11px 9px; border-bottom: 1px solid #edf2f5; vertical-align: middle; }
.cs-table tr:last-child td { border-bottom: 0; }
.cs-table tbody tr:hover { background: #fbfdff; }
.cs-table strong, .cs-table small { display: block; }
.cs-table strong { color: #294b66; font-size: 12px; }
.cs-table small { margin-top: 2px; color: #9aacb9; font-size: 9px; }
.cs-url { display: inline-block; max-width: 260px; overflow: hidden; padding: 2px 6px; border-radius: 5px; background: #f3f7fa; color: #5a7389; font-family: Consolas, Monaco, monospace; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.cs-protocol { padding: 3px 8px; border-radius: 8px; font-size: 9px; white-space: nowrap; }
.cs-protocol.is-rtsp { background: #fff3e6; color: #b97725; }
.cs-protocol.is-webrtc { background: #e8f5ff; color: #247fc2; }
.cs-muted { color: #93a5b4; font-size: 9px; }
.cs-twin { display: inline-flex; padding: 3px 7px; border-radius: 8px; background: #eaf5ff; color: #1676c4; font-size: 9px; white-space: nowrap; }
.cs-status { padding: 3px 8px; border-radius: 8px; font-size: 9px; white-space: nowrap; }
.cs-status.is-on { background: #e8faf3; color: #168b69; }
.cs-status.is-off { background: #f2f5f7; color: #899dac; }
.cs-row-actions { display: flex; gap: 9px; }
.cs-row-actions button { border: 0; background: none; color: #227ac2; font: inherit; font-size: 10px; cursor: pointer; }
.cs-row-actions button.is-danger { color: #d06462; }

.cs-modal-backdrop { position: fixed; inset: 0; z-index: 40; display: flex; align-items: center; justify-content: center; padding: 24px; background: rgba(7, 30, 50, .46); }
.cs-modal { width: min(760px, 94vw); max-height: 88vh; overflow: auto; padding: 20px 22px; border-radius: 16px; background: #fff; box-shadow: 0 24px 60px rgba(5, 27, 45, .32); }
.cs-modal__head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 16px; }
.cs-modal__head h2 { margin: 0; color: #173955; font-size: 18px; }
.cs-modal__head p { margin: 5px 0 0; color: #8095a7; font-size: 10px; line-height: 1.6; }
.cs-close { border: 0; background: transparent; color: #8ea3b3; font-size: 24px; line-height: 1; cursor: pointer; }
.cs-form { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 14px; }
.cs-form label { display: flex; flex-direction: column; gap: 5px; color: #617b90; font-size: 10px; }
.cs-form label > small { color: #96a8b6; font-size: 9px; line-height: 1.55; }
.cs-form input, .cs-form select, .cs-form textarea { width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid #dce8f0; border-radius: 8px; background: #fbfdfe; color: #284967; font: inherit; font-size: 11px; outline: none; }
.cs-form input:focus, .cs-form select:focus, .cs-form textarea:focus { border-color: #8fc4e8; background: #fff; }
.cs-form textarea { resize: vertical; }
.cs-span-2 { grid-column: 1 / span 2; }
.cs-protocol-picker > span { display: block; margin-bottom: 2px; }
.cs-protocol-picker > div { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }
.cs-protocol-picker button { display: flex; flex-direction: column; gap: 3px; padding: 9px 11px; border: 1px solid #e0eaf2; border-radius: 9px; background: #fbfdfe; color: #4a6981; font: inherit; text-align: left; cursor: pointer; }
.cs-protocol-picker button strong { font-size: 11px; }
.cs-protocol-picker button small { color: #92a4b3; font-size: 9px; }
.cs-protocol-picker button.is-active { border-color: #1679d1; background: #f2f9ff; box-shadow: 0 0 0 1px rgba(22,121,209,.12) inset; }
.cs-protocol-picker button.is-active strong { color: #1679d1; }
.cs-form-error { margin: 12px 0 0; padding: 8px 10px; border-radius: 7px; background: #fff2f1; color: #b64c4a; font-size: 10px; }
.cs-modal__foot { display: flex; align-items: center; justify-content: space-between; gap: 15px; margin-top: 18px; padding-top: 14px; border-top: 1px solid #edf2f5; }
.cs-modal__foot > div { display: flex; gap: 8px; flex: 0 0 auto; }
.cs-note { display: inline-flex; align-items: flex-start; gap: 5px; color: #93a5b4; font-size: 9px; line-height: 1.6; }
.cs-note :deep(svg) { flex: 0 0 auto; margin-top: 1px; }

.cs-denied { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 420px; padding: 30px; border: 1px dashed #d8e6f0; border-radius: 15px; background: rgba(255,255,255,.78); text-align: center; }
.cs-denied > :deep(svg) { color: #d39a3b; font-size: 34px; }
.cs-denied strong { color: #315571; font-size: 15px; }
.cs-denied p { margin: 0; color: #8a9dab; font-size: 11px; }
.cs-denied button { margin-top: 8px; height: 34px; padding: 0 15px; border: 0; border-radius: 8px; background: #1679d1; color: #fff; font: inherit; font-size: 11px; cursor: pointer; }

@media (max-width: 900px) {
  .cs-toolbar { flex-direction: column; }
  .cs-toolbar__actions { justify-content: flex-start; width: 100%; }
  .cs-input { width: 100%; }
  .cs-form { grid-template-columns: 1fr; }
  .cs-span-2 { grid-column: auto; }
  .cs-metrics { grid-template-columns: repeat(2, 1fr); }
  .cs-table { min-width: 720px; }
  .cs-modal__foot { flex-direction: column; align-items: stretch; }
  .cs-modal__foot > div { justify-content: flex-end; }
  .cs-protocol-picker > div { grid-template-columns: 1fr; }
}
</style>
