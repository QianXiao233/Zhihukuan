<template>
  <section class="voice-toggle panel-card">
    <header class="panel-head">
      <SoundOutlined class="panel-head__icon" />
      <h3 class="panel-head__title">语音播报</h3>
      <Switch
        class="voice-toggle__switch"
        size="small"
        :checked="enabled"
        :disabled="!supported"
        @change="handleToggle"
      />
    </header>

    <div class="voice-toggle__body" :class="{ 'is-disabled': !enabled }">
      <div class="voice-toggle__row">
        <span class="voice-toggle__label">语速</span>
        <span class="voice-toggle__value">{{ RATE_LABELS[String(rate)] ?? `${rate}×` }}</span>
      </div>

      <Slider
        class="voice-toggle__slider"
        :value="rate"
        :min="0.5"
        :max="1.5"
        :step="0.25"
        :marks="RATE_MARKS"
        :disabled="!supported || !enabled"
        @change="handleRateChange"
      />

      <!-- 五档快捷选择 -->
      <div class="voice-toggle__presets">
        <button
          v-for="preset in RATE_PRESETS"
          :key="preset.value"
          class="voice-toggle__preset"
          :class="{ 'is-active': Math.abs(rate - preset.value) < 0.01 }"
          type="button"
          :disabled="!supported || !enabled"
          @click="props.onRateChange(preset.value)"
        >
          {{ preset.label }}
        </button>
      </div>

      <div class="voice-toggle__voice">
        <span class="voice-toggle__label">音色</span>
        <span class="voice-toggle__voice-name">{{ voiceName || '系统默认' }}</span>
      </div>

      <p v-if="!supported" class="voice-toggle__tip">当前浏览器不支持语音合成</p>
    </div>
  </section>
</template>

<script setup>
import { Slider, Switch } from 'ant-design-vue'
import { SoundOutlined } from '@ant-design/icons-vue'

const props = defineProps({
      enabled: { type: Boolean, required: true },
      supported: { type: Boolean, required: true },
      voiceName: { type: String, required: true },
      rate: { type: Number, required: true },
      onRateChange: { type: Function, required: true },
      onToggle: { type: Function, required: true },
    })

/** 五档语速的文字说明 */
const RATE_LABELS = {
  '0.5': '慢速 0.5×',
  '0.75': '较慢 0.75×',
  '1': '正常 1.0×',
  '1.25': '较快 1.25×',
  '1.5': '快速 1.5×',
}

const RATE_MARKS = {
  0.5: '0.5×',
  1: '1×',
  1.5: '1.5×',
}

/** 五档快捷按钮 */
const RATE_PRESETS = [
  { value: 0.5, label: '0.5×' },
  { value: 0.75, label: '0.75×' },
  { value: 1, label: '1.0×' },
  { value: 1.25, label: '1.25×' },
  { value: 1.5, label: '1.5×' },
]

function handleToggle(checked) {
  props.onToggle(Boolean(checked))
}

/**
 * @param {number | [number, number]} value
 */
function handleRateChange(value) {
  // 非 range 模式下只会有单值，这里做一次收窄
  props.onRateChange(Array.isArray(value) ? value[0] : value)
}
</script>

<style scoped src="./VoiceToggle.css"></style>
