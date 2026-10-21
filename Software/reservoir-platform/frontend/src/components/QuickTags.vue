<template>
  <div class="quick-tags">
    <div class="quick-tags__label">
      <BulbOutlined />
      <span>大家都在问</span>
    </div>
    <div class="quick-tags__list">
      <button
        v-for="tag in tags"
        :key="tag.id"
        class="quick-tags__item"
        type="button"
        @click="onTagClick(tag)"
      >
        {{ tag.text }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { BulbOutlined } from '@ant-design/icons-vue'

defineProps({
      tags: { type: Array, required: true },
      onTagClick: { type: Function, required: true },
    })
</script>

<style scoped src="./QuickTags.css"></style>
