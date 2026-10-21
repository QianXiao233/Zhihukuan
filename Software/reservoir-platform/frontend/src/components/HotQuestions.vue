<template>
  <section class="hot-questions panel-card">
    <header class="panel-head">
      <FireOutlined class="panel-head__icon" />
      <h3 class="panel-head__title">热门问题</h3>
    </header>

    <ul class="hot-questions__list">
      <li v-for="(item, index) in questions" :key="item.id">
        <button class="hot-questions__item" type="button" @click="onQuestionClick(item)">
          <span class="hot-questions__rank" :class="{ 'is-top': index < 3 }">{{ index + 1 }}</span>
          <span class="hot-questions__text">{{ item.text }}</span>
          <span class="hot-questions__heat">
            <FireFilled />
            {{ item.heat }}
          </span>
        </button>
      </li>
    </ul>
  </section>
</template>

<script setup>
import { FireFilled, FireOutlined } from '@ant-design/icons-vue'

defineProps({
      questions: { type: Array, required: true },
      onQuestionClick: { type: Function, required: true },
    })
</script>

<style scoped src="./HotQuestions.css"></style>
