<template>
  <section class="font-size panel-card">
    <header class="panel-head">
      <FontSizeOutlined class="panel-head__icon" />
      <h3 class="panel-head__title">阅读字号</h3>
      <span class="font-size__current">{{ FONT_LABEL[fontSize] }}</span>
    </header>

    <div class="font-size__options">
      <button
        v-for="level in LEVELS"
        :key="level"
        class="font-size__option"
        :class="{ 'is-active': fontSize === level }"
        type="button"
        @click="setFontSize(level)"
      >
        <span :style="{ fontSize: PREVIEW_SIZE[level] }">字</span>
        <span class="font-size__label">{{ FONT_LABEL[level] }}</span>
      </button>
    </div>

    <p class="font-size__tip">调整后全站正文字号会同步变化，并自动保存。</p>
  </section>
</template>

<script setup>
import { FontSizeOutlined } from '@ant-design/icons-vue'
import { FONT_LABEL, fontSize, setFontSize } from '../composables/usePreferences.js'

const LEVELS = ['small', 'normal', 'large', 'xlarge']

/** 按钮上「字」字的预览大小（px） */
const PREVIEW_SIZE = {
  small: '11px',
  normal: '13px',
  large: '15px',
  xlarge: '17px',
}
</script>

<style scoped src="./FontSizePanel.css"></style>
