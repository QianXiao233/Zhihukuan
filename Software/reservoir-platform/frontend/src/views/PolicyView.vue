<template>
  <ViewShell title="政策文档查阅" tag="水利法规 · 行业标准" :icon="FileProtectOutlined">
    <section class="view-card">
      <div class="view-card__toolbar"><h2 class="view-card__title"><SearchOutlined /> 文档检索</h2><div class="policy-filters"><input v-model.trim="query" type="search" placeholder="输入文档名称或编号" /><select v-model="category"><option value="all">全部分类</option><option v-for="item in categories" :key="item" :value="item">{{ item }}</option></select></div></div>
      <ul class="view-list">
        <li v-for="doc in filteredDocs" :key="doc.no" class="view-list__item">
          <div class="view-list__head">
            <span class="view-list__title">{{ doc.title }}</span>
            <span class="view-status" :class="`view-status--${doc.state}`">{{ doc.category }}</span>
            <span class="view-list__time">{{ doc.no }}</span>
          </div>
          <p class="view-list__desc">{{ doc.desc }}</p>
        </li>
      </ul>
    </section>

    <section class="view-card">
      <h2 class="view-card__title"><FileProtectOutlined /> 常用罚则与责任条款速查</h2>
      <table class="view-table">
        <thead>
          <tr>
            <th>情形</th>
            <th>依据</th>
            <th>处理要点</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in RULES" :key="row.case">
            <td>{{ row.case }}</td>
            <td>{{ row.basis }}</td>
            <td>{{ row.action }}</td>
          </tr>
        </tbody>
      </table>
    </section>
  </ViewShell>
</template>

<script setup>
import { computed, ref } from 'vue'
import {
  FileProtectOutlined,
  SearchOutlined,
} from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'

const DOCS = [
  {
    no: 'SL 258-2017',
    title: '水库大坝安全评价导则',
    category: '行业标准',
    state: 'info',
    desc: '规定了大坝安全评价的分类、评价内容、评价方法与评价结论的判定标准，是开展大坝安全鉴定的主要技术依据。',
  },
  {
    no: 'SL 601-2013',
    title: '混凝土坝安全监测技术规范',
    category: '行业标准',
    state: 'info',
    desc: '涵盖变形、渗流、应力应变与环境量等监测项目的布置原则、测次要求与资料分析方法。',
  },
  {
    no: '国务院令第 78 号',
    title: '水库大坝安全管理条例',
    category: '行政法规',
    state: 'warn',
    desc: '明确了大坝管理单位的巡查、观测、维修养护义务，以及险情报告与应急处置的法定要求。',
  },
  {
    no: '水法',
    title: '中华人民共和国水法',
    category: '法律',
    state: 'warn',
    desc: '确立了水资源的规划、开发利用、保护与管理的法律框架，是水利行业的基本法律。',
  },
  {
    no: 'SL 706-2015',
    title: '水库调度规程编制导则',
    category: '行业标准',
    state: 'info',
    desc: '规定了防洪调度、兴利调度与生态调度的编制要求，是编制水库调度规程的技术依据。',
  },
]

const RULES = [
  {
    case: '未按规定巡查、观测大坝',
    basis: '《水库大坝安全管理条例》',
    action: '责令限期改正，逾期不改的可处罚款；造成后果的依法追究责任。',
  },
  {
    case: '擅自开闸泄洪、未发布预警',
    basis: '《水库大坝安全管理条例》《水法》',
    action: '属严重违规行为，必须立即制止并上报防汛主管部门。',
  },
  {
    case: '侵占、损毁水利工程设施',
    basis: '《水法》',
    action: '责令停止违法行为、恢复原状，并依法承担赔偿责任。',
  },
  {
    case: '未按规定下泄生态流量',
    basis: '生态调度相关规程',
    action: '责令整改并补足下泄水量，纳入年度考核。',
  },
]

const query = ref('')
const category = ref('all')
const categories = [...new Set(DOCS.map((doc) => doc.category))]
const filteredDocs = computed(() => DOCS.filter((doc) => {
  const matchesCategory = category.value === 'all' || doc.category === category.value
  const haystack = `${doc.title} ${doc.no} ${doc.desc}`.toLowerCase()
  return matchesCategory && (!query.value || haystack.includes(query.value.toLowerCase()))
}))
</script>

<style scoped>
.view-card__toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px}.view-card__toolbar .view-card__title{margin-bottom:14px}.policy-filters{display:flex;gap:7px}.policy-filters input,.policy-filters select{height:30px;padding:0 9px;border:1px solid #dce8f0;border-radius:7px;background:#fbfdfe;color:#58738a;font-size:10px}.policy-filters input{width:190px}@media(max-width:700px){.view-card__toolbar{align-items:flex-start;flex-direction:column}.policy-filters{width:100%}.policy-filters input{flex:1}}
</style>
