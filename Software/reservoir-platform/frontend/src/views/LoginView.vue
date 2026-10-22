<template>
  <main class="login-page">
    <div class="login-backdrop"></div>
    <section class="login-layout">
      <div class="login-intro">
        <div class="login-brand-mark"><span></span><span></span><span></span></div>
        <p class="login-kicker">RESERVOIR DIGITAL OPERATIONS</p>
        <h1>智御安澜</h1>
        <p class="login-subtitle">水库数字化运营工作台</p>
        <div class="login-intro__line"></div>
        <p class="login-intro__desc">统一接入水情监测、巡检台账、防汛调度、生态管护与无人艇作业，让水库管理更及时、更可靠。</p>
        <div class="login-points"><span><i></i>实时数据接入</span><span><i></i>智能预警分析</span><span><i></i>无人艇协同</span></div>
      </div>

      <form class="login-card" @submit.prevent="handleLogin">
        <div class="login-card__head"><span>平台登录</span><small>登录后进入水库运营工作台</small></div>
        <div v-if="globalError" class="login-error">{{ globalError }}</div>
        <label class="login-field"><span>用户名</span><input v-model.trim="form.username" autocomplete="username" placeholder="请输入用户名" @blur="validateUsername" /><em v-if="usernameError">{{ usernameError }}</em></label>
        <label class="login-field"><span>密码</span><input v-model="form.password" type="password" autocomplete="current-password" placeholder="请输入密码" @blur="validatePassword" /><em v-if="passwordError">{{ passwordError }}</em></label>
        <label class="login-remember"><input v-model="remember" type="checkbox" />记住登录状态</label>
        <button class="login-submit" type="submit" :disabled="loading"><span v-if="loading" class="login-spinner"></span>{{ loading ? '登录中…' : '登录平台' }}</button>
        <p class="login-tip">账号由水库管理中心统一分配，用户名区分大小写</p>
      </form>
    </section>
    <footer class="login-footer">智御安澜 · 中小型水库数字化运营平台</footer>
  </main>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { login } from '../api/auth.js'
import { startNoticeChannel } from '../utils/noticeChannel.js'

const router = useRouter()
const route = useRoute()
const form = ref({ username: '', password: '' })
const remember = ref(true)
const loading = ref(false)
const globalError = ref('')
const usernameError = ref('')
const passwordError = ref('')

function validateUsername() {
  usernameError.value = form.value.username ? '' : '请输入用户名'
  return !usernameError.value
}

function validatePassword() {
  passwordError.value = form.value.password ? '' : '请输入密码'
  return !passwordError.value
}

async function handleLogin() {
  if (!validateUsername() || !validatePassword()) {
    globalError.value = '请先完善登录信息'
    return
  }
  globalError.value = ''
  loading.value = true
  try {
    const result = await login(form.value)
    if (!result.success) {
      globalError.value = result.message || '用户名或密码错误'
      return
    }
    localStorage.setItem('token', result.token || '')
    localStorage.setItem('username', result.username || form.value.username)
    if (result.level !== undefined) localStorage.setItem('level', String(result.level))
    startNoticeChannel()
    if (!remember.value) sessionStorage.setItem('reservoir-session', '1')
    const redirect = typeof route.query.redirect === 'string' && route.query.redirect !== '/' ? route.query.redirect : '/monitor'
    await router.replace(redirect)
  } catch (error) {
    globalError.value = error instanceof Error ? error.message : '网络错误，请重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page{position:relative;display:flex;align-items:center;justify-content:center;width:100%;height:100vh;overflow:hidden;background:#061b31;color:#173955}.login-backdrop{position:absolute;inset:0;background:linear-gradient(90deg,rgba(3,20,39,.9),rgba(3,29,52,.58)),url('../assets/login/background_new.png') center/cover;filter:saturate(.82)}.login-page:after{content:'';position:absolute;inset:0;background:radial-gradient(circle at 75% 30%,rgba(39,190,229,.25),transparent 34%),linear-gradient(120deg,transparent 40%,rgba(11,96,151,.2));pointer-events:none}.login-layout{position:relative;z-index:1;display:grid;grid-template-columns:minmax(320px,1fr) 420px;align-items:center;gap:110px;width:min(1040px,calc(100% - 56px))}.login-intro{color:#effbff}.login-brand-mark{display:flex;align-items:center;gap:3px;width:53px;height:53px;justify-content:center;border-radius:16px;background:linear-gradient(140deg,#27d1e7,#1b6fe4);box-shadow:0 12px 28px rgba(22,175,229,.28)}.login-brand-mark span{width:6px;border-radius:5px;background:#fff;transform:skewY(-28deg)}.login-brand-mark span:nth-child(1){height:20px}.login-brand-mark span:nth-child(2){height:31px}.login-brand-mark span:nth-child(3){height:23px}.login-kicker{margin:28px 0 13px;color:#76cce6;font-size:10px;letter-spacing:.18em}.login-intro h1{margin:0;font-size:48px;letter-spacing:.1em}.login-subtitle{margin:7px 0 0;color:#a4ccdf;font-size:16px;letter-spacing:.15em}.login-intro__line{width:65px;height:3px;margin:27px 0 20px;border-radius:3px;background:linear-gradient(90deg,#26cae1,#2d81ea)}.login-intro__desc{max-width:420px;margin:0;color:#a7c6d7;font-size:14px;line-height:2}.login-points{display:flex;gap:18px;margin-top:32px;color:#d2ecf5;font-size:11px}.login-points span{display:inline-flex;align-items:center;gap:6px}.login-points i{width:6px;height:6px;border-radius:50%;background:#2fd4ac;box-shadow:0 0 0 4px rgba(47,212,172,.12)}.login-card{padding:35px 35px 27px;border:1px solid rgba(179,224,239,.55);border-radius:20px;background:rgba(250,254,255,.94);box-shadow:0 24px 70px rgba(0,10,28,.3);backdrop-filter:blur(14px)}.login-card__head{margin-bottom:27px}.login-card__head span{display:block;color:#183c59;font-size:24px;font-weight:700}.login-card__head small{display:block;margin-top:6px;color:#8297a9;font-size:11px}.login-error{margin-bottom:16px;padding:9px 11px;border:1px solid #ffd0cd;border-radius:8px;background:#fff2f1;color:#d34945;font-size:11px}.login-field{display:block;margin-bottom:18px}.login-field>span{display:block;margin-bottom:7px;color:#44637b;font-size:12px;font-weight:600}.login-field input{width:100%;height:44px;padding:0 13px;border:1px solid #d6e2eb;border-radius:9px;outline:0;background:#fbfdff;color:#234662;font:inherit;font-size:13px;transition:.2s}.login-field input:focus{border-color:#339ee1;box-shadow:0 0 0 4px rgba(51,158,225,.11)}.login-field em{display:block;margin-top:5px;color:#d34c4c;font-size:10px;font-style:normal}.login-remember{display:flex;align-items:center;gap:7px;color:#7d92a3;font-size:11px}.login-remember input{accent-color:#2187dc}.login-submit{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;height:45px;margin-top:21px;border:0;border-radius:9px;background:linear-gradient(105deg,#1f91e2,#166bd2);color:#fff;font:inherit;font-size:14px;font-weight:650;letter-spacing:.08em;cursor:pointer;box-shadow:0 8px 18px rgba(27,121,215,.25);transition:.2s}.login-submit:hover:not(:disabled){transform:translateY(-1px);box-shadow:0 11px 23px rgba(27,121,215,.32)}.login-submit:disabled{opacity:.65;cursor:wait}.login-spinner{width:14px;height:14px;border:2px solid rgba(255,255,255,.45);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite}.login-tip{margin:19px 0 0;color:#9aabb8;font-size:10px;text-align:center}.login-footer{position:absolute;z-index:1;bottom:24px;color:#8aafc1;font-size:10px;letter-spacing:.08em}@keyframes spin{to{transform:rotate(360deg)}}@media(max-width:780px){.login-layout{grid-template-columns:1fr;gap:20px;width:min(430px,calc(100% - 30px))}.login-intro{text-align:center}.login-brand-mark{margin:auto}.login-kicker{margin-top:16px}.login-intro h1{font-size:36px}.login-intro__line{margin:17px auto 12px}.login-intro__desc,.login-points{display:none}.login-card{padding:27px 24px 22px}.login-footer{bottom:12px;font-size:9px}}
</style>
