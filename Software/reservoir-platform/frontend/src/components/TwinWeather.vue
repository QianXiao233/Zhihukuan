<template>
  <div ref="wrapEl" class="twin-weather-wrap">
    <button
      type="button"
      class="twin-weather"
      :class="{ 'is-empty': !weather, 'is-open': open }"
      :disabled="!weather"
      :aria-expanded="open"
      aria-label="查看详细天气"
      @click="open = !open"
    >
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
      <i class="twin-weather__chevron" :class="{ 'is-open': open }" aria-hidden="true"></i>
    </button>

    <transition name="twin-weather-pop">
      <section v-if="open && weather" class="twin-weather-panel" @click.stop>
        <header class="twin-weather-panel__head">
          <div>
            <strong>{{ weather.text }} {{ format(weather.temp, 0) }}℃</strong>
            <small>体感 {{ format(weather.feelsLike, 1) }}℃ · {{ windText }}</small>
          </div>
          <button type="button" aria-label="关闭天气详情" @click="open = false">×</button>
        </header>

        <div class="twin-weather-panel__grid">
          <div><span>今日最高</span><b>{{ format(weather.tempMax, 0) }}℃</b></div>
          <div><span>今日最低</span><b>{{ format(weather.tempMin, 0) }}℃</b></div>
          <div><span>湿度</span><b>{{ value(weather.humidity, 0, '%') }}</b></div>
          <div><span>气压</span><b>{{ value(weather.pressure, 0, ' hPa') }}</b></div>
          <div><span>能见度</span><b>{{ value(weather.visibilityKm, 1, ' km') }}</b></div>
          <div><span>降水量</span><b>{{ value(weather.precipitation, 1, ' mm') }}</b></div>
          <div><span>降水概率</span><b>{{ value(weather.precipProbability, 0, '%') }}</b></div>
          <div><span>紫外线</span><b>{{ uvText }}</b></div>
          <div><span>云量</span><b>{{ value(weather.cloudCover, 0, '%') }}</b></div>
          <div><span>风速</span><b>{{ value(weather.windSpeed, 1, ' m/s') }}</b></div>
          <div><span>阵风</span><b>{{ value(weather.windGust, 1, ' m/s') }}</b></div>
          <div><span>风向</span><b>{{ weather.windDir || '—' }}</b></div>
        </div>

        <dl class="twin-weather-panel__list">
          <div><dt>日出 / 日落</dt><dd>{{ clock(weather.sunrise) }} / {{ clock(weather.sunset) }}</dd></div>
          <div><dt>白天 / 夜间</dt><dd>{{ weather.dayText || '—' }} / {{ weather.nightText || '—' }}</dd></div>
          <div><dt>更新时间</dt><dd>{{ weather.observedAt || '—' }}{{ weather.stale ? '（缓存）' : '' }}</dd></div>
        </dl>

        <footer>数据来源：和风天气</footer>
      </section>
    </transition>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { getWeather } from '../api/manageApi.js'

const weather = ref(null)
const open = ref(false)
const wrapEl = ref(null)

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

const uvText = computed(() => {
  const uv = weather.value?.uvIndex
  if (uv == null || Number.isNaN(Number(uv))) return '—'
  const value = Number(uv)
  const label = value <= 2 ? '弱' : value <= 5 ? '中等' : value <= 7 ? '强' : value <= 10 ? '很强' : '极强'
  return `${value} ${label}`
})

function format(value, digits = 0) {
  return value == null || Number.isNaN(Number(value)) ? '--' : Number(value).toFixed(digits)
}

function value(input, digits = 0, unit = '') {
  return input == null || Number.isNaN(Number(input)) ? '—' : `${Number(input).toFixed(digits)}${unit}`
}

function clock(input) {
  if (!input) return '—'
  const date = new Date(input)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })
}

async function load() {
  try {
    const result = await getWeather()
    weather.value = result.data || null
  } catch {
    // 保留上一帧；首次失败时显示加载占位
  }
}

function onDocumentClick(event) {
  if (open.value && wrapEl.value && !wrapEl.value.contains(event.target)) {
    open.value = false
  }
}

let timer = 0
onMounted(() => {
  void load()
  timer = window.setInterval(load, 10 * 60 * 1000)
  document.addEventListener('click', onDocumentClick)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
  document.removeEventListener('click', onDocumentClick)
})
</script>

<style scoped>
.twin-weather-wrap {
  position: absolute;
  top: 12px;
  left: 50%;
  z-index: 4;
  transform: translateX(-50%);
  pointer-events: none;
}

.twin-weather {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 150px;
  padding: 6px 10px;
  border: 1px solid rgba(126, 214, 244, .24);
  border-radius: 9px;
  background: rgba(4, 24, 35, .72);
  color: #e9fbff;
  font: inherit;
  text-align: left;
  box-shadow: 0 6px 18px rgba(0, 0, 0, .22);
  backdrop-filter: blur(6px);
  cursor: pointer;
  pointer-events: auto;
  transition: border-color .15s ease, background .15s ease;
}

.twin-weather:hover,
.twin-weather.is-open {
  border-color: rgba(126, 224, 255, .6);
  background: rgba(6, 38, 54, .86);
}

.twin-weather:disabled {
  cursor: default;
  opacity: .8;
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

.twin-weather__chevron {
  flex: 0 0 auto;
  width: 6px;
  height: 6px;
  margin-left: 2px;
  border-right: 1px solid #9fd8ee;
  border-bottom: 1px solid #9fd8ee;
  transform: rotate(45deg) translateY(-1px);
  transition: transform .15s ease;
}

.twin-weather__chevron.is-open {
  transform: rotate(-135deg) translateY(-1px);
}

.twin-weather.is-empty {
  opacity: .82;
}

.twin-weather-panel {
  position: absolute;
  top: calc(100% + 7px);
  left: 50%;
  width: min(360px, calc(100vw - 48px));
  max-height: 390px;
  overflow: auto;
  padding: 11px 12px 9px;
  border: 1px solid rgba(111, 198, 232, .32);
  border-radius: 11px;
  background: rgba(5, 26, 38, .97);
  color: #e7f6ff;
  box-shadow: 0 16px 42px rgba(0, 0, 0, .45);
  transform: translateX(-50%);
  pointer-events: auto;
}

.twin-weather-panel__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.twin-weather-panel__head strong {
  display: block;
  font-size: 14px;
  font-weight: 600;
}

.twin-weather-panel__head small {
  display: block;
  margin-top: 3px;
  color: #9dbccb;
  font-size: 9px;
}

.twin-weather-panel__head > button {
  flex: 0 0 auto;
  width: 24px;
  height: 24px;
  border: 1px solid rgba(143, 196, 220, .2);
  border-radius: 6px;
  background: rgba(8, 40, 55, .7);
  color: #b9d8e7;
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
}

.twin-weather-panel__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
  margin-top: 11px;
}

.twin-weather-panel__grid > div {
  padding: 6px 7px;
  border-radius: 7px;
  background: rgba(9, 42, 58, .7);
}

.twin-weather-panel__grid span {
  display: block;
  color: #8fa9b8;
  font-size: 8px;
}

.twin-weather-panel__grid b {
  display: block;
  margin-top: 3px;
  color: #dff8ff;
  font-size: 11px;
  font-weight: 600;
  white-space: nowrap;
}

.twin-weather-panel__list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin: 10px 0 0;
  padding: 8px 0 0;
  border-top: 1px solid rgba(111, 198, 232, .14);
}

.twin-weather-panel__list > div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
}

.twin-weather-panel__list dt,
.twin-weather-panel__list dd {
  margin: 0;
  font-size: 9px;
}

.twin-weather-panel__list dt { color: #8fa9b8; }
.twin-weather-panel__list dd { color: #c7e3f0; text-align: right; }

.twin-weather-panel footer {
  margin-top: 8px;
  color: #6f8b9b;
  font-size: 8px;
  text-align: right;
}

.twin-weather-pop-enter-active,
.twin-weather-pop-leave-active {
  transition: opacity .14s ease, transform .14s ease;
}

.twin-weather-pop-enter-from,
.twin-weather-pop-leave-to {
  opacity: 0;
  transform: translateX(-50%) translateY(-4px);
}
</style>
