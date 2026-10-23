<template>
  <ViewShell title="监控中心" :tag="headerTag" :icon="VideoCameraOutlined">
    <div class="vc-page">
      <section class="vc-toolbar">
        <div class="vc-summary">
          <span class="vc-summary__pulse" :class="{ 'is-live': liveCount > 0 }"><i></i></span>
          <div>
            <strong>{{ enabledSources.length }} 路视频画面</strong>
            <small>在线 {{ liveCount }} · 连接中 {{ connectingCount }} · 异常 {{ errorCount }}</small>
          </div>
        </div>
        <div class="vc-toolbar__right">
          <div class="vc-layout" role="group" aria-label="画面布局">
            <button
              v-for="option in LAYOUTS"
              :key="option.value"
              type="button"
              class="vc-layout__btn"
              :class="{ 'is-active': columns === option.value }"
              :title="option.title"
              @click="setColumns(option.value)"
            >
              {{ option.label }}
            </button>
          </div>
          <button type="button" class="vc-action" :disabled="loading" @click="reload">
            <ReloadOutlined :class="{ 'is-spinning': loading }" />
            <span>刷新画面</span>
          </button>
          <button v-if="canManage" type="button" class="vc-action vc-action--primary" @click="go('camera-sources')">
            <SettingOutlined />
            <span>画面来源设置</span>
          </button>
        </div>
      </section>

      <p v-if="error" class="vc-error"><WarningOutlined /> {{ error }}<button type="button" @click="reload">重试</button></p>

      <section v-if="loading && !sources.length" class="vc-empty">
        <LoadingOutlined spin />
        <strong>正在读取画面来源…</strong>
      </section>

      <section v-else-if="!enabledSources.length" class="vc-empty">
        <span class="vc-empty__icon"><VideoCameraOutlined /></span>
        <strong>{{ error ? '画面来源读取失败' : sources.length ? '所有画面都已停用' : '还没有配置监控画面' }}</strong>
        <p>{{ error ? '请检查后端服务是否启动、画面来源接口是否可用，然后点击刷新。' : sources.length ? '启用画面来源后，这里会自动显示视频墙。' : '管理员可以添加摄像机 RTSP 地址，或直接填写 WebRTC（WHEP）播放地址。' }}</p>
        <button v-if="canManage && !error" type="button" class="vc-empty__btn" @click="go('camera-sources')"><PlusOutlined /> 配置画面来源</button>
        <small v-else-if="!canManage">请联系系统管理员配置画面来源。</small>
      </section>

      <section v-else class="vc-grid" :style="{ '--vc-cols': effectiveColumns }">
        <VideoTile
          v-for="source in enabledSources"
          :key="`${source.sourceId}-${reloadToken}`"
          :source="source"
          :active="source.enabled !== 0"
          @status="onTileStatus"
        />
      </section>

      <footer class="vc-footer">
        <span><InfoCircleOutlined /> 浏览器不直接播放 RTSP：RTSP 画面需经视频网关转成 WebRTC 后接入，WebRTC 画面使用 WHEP 地址。</span>
        <div>
          <button type="button" @click="go('alarm-center')"><AlertOutlined /> 告警中心</button>
          <button type="button" @click="go('monitor-detail')"><DashboardOutlined /> 实时监测</button>
        </div>
      </footer>
    </div>
  </ViewShell>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertOutlined,
  DashboardOutlined,
  InfoCircleOutlined,
  LoadingOutlined,
  PlusOutlined,
  ReloadOutlined,
  SettingOutlined,
  VideoCameraOutlined,
  WarningOutlined,
} from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import VideoTile from '../components/VideoTile.vue'
import { listCameraSources } from '../api/manageApi.js'

const router = useRouter()
const sources = ref([])
const loading = ref(false)
const error = ref('')
const reloadToken = ref(0)
const tileStates = ref({})
const columns = ref(Number(localStorage.getItem('platform.videoLayout')) || 2)

const LAYOUTS = [
  { value: 1, label: '1×1', title: '单画面' },
  { value: 2, label: '2×2', title: '四宫格' },
  { value: 3, label: '3×3', title: '九宫格' },
  { value: 4, label: '4×4', title: '十六宫格' },
]

const accountLevel = Number(localStorage.getItem('level') ?? 1)
const canManage = accountLevel === 0 || accountLevel >= 3

const enabledSources = computed(() => sources.value.filter((source) => source.enabled !== 0))
const effectiveColumns = computed(() => Math.min(columns.value, Math.max(1, enabledSources.value.length)))

function stateOf(source) {
  return tileStates.value[source.sourceId]?.status || 'idle'
}
const liveCount = computed(() => enabledSources.value.filter((source) => stateOf(source) === 'live').length)
const connectingCount = computed(() => enabledSources.value.filter((source) => stateOf(source) === 'connecting').length)
const errorCount = computed(() => enabledSources.value.filter((source) => stateOf(source) === 'error').length)

const headerTag = computed(() => {
  if (loading.value) return '正在读取画面来源'
  if (error.value) return '画面来源读取失败'
  if (!enabledSources.value.length) return '暂无启用的视频画面'
  return `${enabledSources.value.length} 路画面 · ${liveCount.value} 路在线`
})

function onTileStatus({ id, status }) {
  if (!id) return
  tileStates.value = { ...tileStates.value, [id]: { status, at: Date.now() } }
}

function setColumns(value) {
  columns.value = value
  localStorage.setItem('platform.videoLayout', String(value))
}

function go(name) {
  void router.push({ name })
}

async function reload() {
  if (loading.value) return
  loading.value = true
  error.value = ''
  tileStates.value = {}
  try {
    const result = await listCameraSources()
    sources.value = result.data || []
    reloadToken.value += 1
  } catch (e) {
    error.value = e.message || '画面来源读取失败'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void reload()
})
</script>

<style scoped>
.vc-page { display: flex; flex-direction: column; gap: 14px; min-width: 900px; min-height: 100%; }
.vc-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 11px 14px; border: 1px solid #e2ebf3; border-radius: 13px; background: rgba(255,255,255,.94); box-shadow: 0 6px 16px rgba(31,80,117,.05); }
.vc-summary { display: flex; align-items: center; gap: 10px; min-width: 0; }
.vc-summary__pulse { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; flex: 0 0 30px; border-radius: 9px; background: #eef5f8; }
.vc-summary__pulse i { width: 8px; height: 8px; border-radius: 50%; background: #a8b8c4; }
.vc-summary__pulse.is-live { background: #e8fbf3; }
.vc-summary__pulse.is-live i { background: #22bd8d; box-shadow: 0 0 0 4px rgba(34,189,141,.13); animation: vc-pulse 2s ease-in-out infinite; }
.vc-summary strong, .vc-summary small { display: block; }
.vc-summary strong { color: #1b3e5c; font-size: 13px; font-weight: 650; }
.vc-summary small { margin-top: 2px; color: #8c9fae; font-size: 9px; }
.vc-toolbar__right { display: flex; align-items: center; gap: 8px; flex: 0 0 auto; }
.vc-layout { display: inline-flex; gap: 2px; padding: 3px; border: 1px solid #e3edf4; border-radius: 9px; background: #f6fafc; }
.vc-layout__btn { min-width: 38px; height: 26px; border: 0; border-radius: 6px; background: transparent; color: #7890a3; font: inherit; font-size: 9px; cursor: pointer; }
.vc-layout__btn:hover { color: #2b7fba; }
.vc-layout__btn.is-active { background: #1679d1; color: #fff; box-shadow: 0 3px 8px rgba(22,121,209,.22); }
.vc-action { display: inline-flex; align-items: center; gap: 5px; height: 33px; padding: 0 11px; border: 1px solid #dbe7f0; border-radius: 8px; background: #fff; color: #5e7d94; font: inherit; font-size: 10px; cursor: pointer; white-space: nowrap; }
.vc-action:hover:not(:disabled) { border-color: #9fcde8; color: #1d79bd; }
.vc-action:disabled { opacity: .65; cursor: progress; }
.vc-action--primary { border-color: #1679d1; background: #1679d1; color: #fff; box-shadow: 0 6px 14px rgba(22,121,209,.2); }
.vc-action--primary:hover:not(:disabled) { border-color: #0f6dc3; background: #0f6dc3; color: #fff; }

.vc-error { display: flex; align-items: center; gap: 7px; margin: 0; padding: 9px 12px; border-radius: 9px; background: #fff2f1; color: #b64c4a; font-size: 11px; }
.vc-error button { margin-left: auto; padding: 3px 9px; border: 1px solid #ecc9c6; border-radius: 6px; background: #fff; color: #b64c4a; font: inherit; font-size: 10px; cursor: pointer; }

.vc-grid { display: grid; grid-template-columns: repeat(var(--vc-cols, 2), minmax(0, 1fr)); gap: 13px; align-content: start; }

.vc-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px; min-height: 420px; padding: 30px; border: 1px dashed #d8e6f0; border-radius: 15px; background: rgba(255,255,255,.72); text-align: center; }
.vc-empty__icon { display: inline-flex; align-items: center; justify-content: center; width: 56px; height: 56px; border-radius: 16px; background: #eaf4fb; color: #3b93ca; font-size: 26px; }
.vc-empty > :deep(svg) { color: #4b9dcc; font-size: 28px; }
.vc-empty strong { color: #315571; font-size: 14px; font-weight: 600; }
.vc-empty p { max-width: 430px; margin: 0; color: #8699aa; font-size: 10px; line-height: 1.8; }
.vc-empty small { color: #9aabb9; font-size: 10px; }
.vc-empty__btn { display: inline-flex; align-items: center; gap: 5px; height: 34px; margin-top: 6px; padding: 0 14px; border: 0; border-radius: 8px; background: #1679d1; color: #fff; font: inherit; font-size: 11px; cursor: pointer; box-shadow: 0 6px 15px rgba(22,121,209,.2); }
.vc-empty__btn:hover { background: #0f6dc3; }

.vc-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: auto; padding: 8px 4px 0; color: #91a4b3; font-size: 9px; }
.vc-footer > span { display: inline-flex; align-items: flex-start; gap: 5px; line-height: 1.6; }
.vc-footer > span :deep(svg) { flex: 0 0 auto; margin-top: 1px; color: #9db3c4; }
.vc-footer > div { display: flex; gap: 13px; flex: 0 0 auto; }
.vc-footer button { display: inline-flex; align-items: center; gap: 4px; border: 0; background: transparent; color: #7fa2c0; font: inherit; font-size: 9px; cursor: pointer; white-space: nowrap; }
.vc-footer button:hover { color: #1676e8; }
.is-spinning { animation: vc-spin .8s linear infinite; }
@keyframes vc-spin { to { transform: rotate(360deg); } }
@keyframes vc-pulse { 0%, 100% { opacity: 1; } 50% { opacity: .45; } }

@media (max-width: 1280px) {
  .vc-toolbar { flex-wrap: wrap; }
  .vc-toolbar__right { flex-wrap: wrap; }
  .vc-page { min-width: 760px; }
  .vc-grid { gap: 10px; }
}
@media (max-width: 900px) {
  .vc-page { min-width: 0; gap: 10px; }
  .vc-grid { grid-template-columns: 1fr; }
  .vc-footer { flex-direction: column; align-items: flex-start; }
  .vc-toolbar { padding: 10px; gap: 10px; }
  .vc-toolbar__right { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 7px; }
  .vc-layout { grid-column: 1 / -1; justify-content: space-between; }
  .vc-layout__btn { flex: 1; }
  .vc-action { justify-content: center; }
  .vc-summary strong { font-size: 12px; }
}
</style>
