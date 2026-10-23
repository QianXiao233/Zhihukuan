<template>
  <div ref="host" class="dam-twin-scene" :class="{ 'is-failed': failed }" aria-hidden="true">
    <div v-if="loading" class="dam-twin-scene__tip">三维沙盘加载中…</div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { createDamScene } from '../three/damScene.js'

const props = defineProps({
  level: { type: Number, default: null },
  thresholds: { type: Object, default: () => ({}) },
  gates: { type: Array, default: () => [] },
  alarm: { type: Number, default: 0 },
  quality: { type: String, default: 'auto' },
})

const emit = defineEmits(['status', 'label-click'])

const host = ref(null)
const loading = ref(true)
const failed = ref(false)

let scene = null
let disposed = false

function resolveModelUrl() {
  const base = import.meta.env.BASE_URL || '/'
  return `${base.endsWith('/') ? base : `${base}/`}models/dam.glb`
}

function pushData() {
  if (!scene) return
  scene.setData({
    level: Number.isFinite(props.level) ? props.level : null,
    thresholds: props.thresholds || {},
    gates: Array.isArray(props.gates) ? props.gates : [],
    alarm: Number(props.alarm) || 0,
  })
}

async function init() {
  if (!host.value) return
  try {
    scene = createDamScene({
      container: host.value,
      quality: props.quality,
      showCameraPoints: false,
      onLabelClick: (key) => emit('label-click', key),
    })
    pushData()
    scene.start()

    const result = await scene.loadExternalModel(resolveModelUrl())
    if (disposed || !scene) return
    scene.overview()
    loading.value = false
    emit('status', {
      failed: false,
      modelLoaded: result.ok,
      gates: result.gates,
      cameras: result.cameras,
    })
  } catch (err) {
    loading.value = false
    failed.value = true
    scene?.dispose?.()
    scene = null
    emit('status', { failed: true, error: String(err?.message || err) })
  }
}

watch(
  () => [props.level, props.thresholds, props.gates, props.alarm],
  pushData,
  { deep: true },
)

onMounted(() => { void init() })

onBeforeUnmount(() => {
  disposed = true
  scene?.dispose()
  scene = null
})

defineExpose({
  resize: () => scene?.resize(),
  overview: () => scene?.overview(),
  project: (point) => scene?.projectPoint(point),
  setLabelState: (key, state) => scene?.setLabelState(key, state),
})
</script>

<style scoped>
.dam-twin-scene {
  position: absolute;
  inset: 0;
  z-index: 1;
  overflow: hidden;
  background:
    radial-gradient(120% 90% at 20% 0%, rgba(77, 166, 205, 0.42), transparent 60%),
    radial-gradient(90% 70% at 80% 10%, rgba(255, 214, 160, 0.16), transparent 62%),
    linear-gradient(180deg, #0d2b38 0%, #0a2029 48%, #07161d 100%);
}

.dam-twin-scene.is-failed {
  display: none;
}

.dam-twin-scene :deep(canvas) {
  display: block;
  width: 100%;
  height: 100%;
}

.dam-twin-scene__tip {
  position: absolute;
  inset: 0;
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9fd8ee;
  font-size: 12px;
  letter-spacing: 0.08em;
  background: rgba(6, 22, 30, 0.55);
  pointer-events: none;
}
</style>
