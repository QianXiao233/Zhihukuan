<template>
  <div class="twin-weather" :class="{ 'is-empty': !weather }" aria-live="polite">
    <span class="twin-weather__icon">{{ weather ? icon : '🌤️' }}</span>
    <div class="twin-weather__copy">
      <strong v-if="weather">{{ weather.text }} {{ format(weather.temp, 0) }}℃</strong>
      <strong v-else>天气加载中</strong>
      <small v-if="weather">
        <template v-if="weather.tempMin != null && weather.tempMax != null">{{ format(weather.tempMin, 0) }}~{{ format(weather.tempMax, 0) }}℃ · </template>
        {{ windText }}<template v-if="weather.stale"> · 缓存</template>
      </small>
      <small v-else>和风天气</small>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getWeather } from '../api/manageApi.js'

const weather = ref(null)

const icon = computed(() => {
  const text = weather.value?.text || ''
  if (text.includes('雷')) return '⛈️'
  if (text.includes('雪')) return '❄️'
  if (text.includes('雨')) return '🌧️'
  if (text.includes('雾') || text.includes('霾')) return '🌫️'
  if (text.includes('阴')) return '☁️'
  if (text.includes('多云')) return '⛅'
  if (text.includes('晴')) return '☀️'
  return '🌤️'
})

const windText = computed(() => {
  if (!weather.value) return ''
  const dir = weather.value.windDir || ''
  const scale = weather.value.windScale
  return `${dir}${scale == null ? '' : `${scale}级`}`.trim() || '风力未知'
})

function format(value, digits = 0) {
  return value == null || Number.isNaN(Number(value)) ? '--' : Number(value).toFixed(digits)
}

async function load() {
  try {
    const result = await getWeather()
    weather.value = result.data || null
  } catch {
    // 保留上一帧；首次失败时显示加载占位
  }
}

let timer = 0
onMounted(() => {
  void load()
  timer = window.setInterval(load, 10 * 60 * 1000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.twin-weather {
  position: absolute;
  top: 12px;
  left: 50%;
  z-index: 4;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: calc(100% - 150px);
  padding: 6px 10px;
  border: 1px solid rgba(126, 214, 244, .24);
  border-radius: 9px;
  background: rgba(4, 24, 35, .72);
  color: #e9fbff;
  box-shadow: 0 6px 18px rgba(0, 0, 0, .22);
  backdrop-filter: blur(6px);
  transform: translateX(-50%);
  pointer-events: none;
}

.twin-weather__icon {
  flex: 0 0 auto;
  font-size: 17px;
  line-height: 1;
}

.twin-weather__copy {
  min-width: 0;
  line-height: 1.25;
}

.twin-weather__copy strong {
  display: block;
  overflow: hidden;
  font-size: 10px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.twin-weather__copy small {
  display: block;
  overflow: hidden;
  margin-top: 2px;
  color: #9dbccb;
  font-size: 8px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.twin-weather.is-empty {
  opacity: .82;
}
</style>
