/**
 * 语音合成 hook：浏览器 speechSynthesis 朗读 AI 回答。
 * 朗读期间 speaking = true，驱动数字人嘴型开合；
 * onboundary（词边界）回调用于进一步细化口型节奏。
 */
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { voiceEnabled, voiceRate } from '../composables/usePreferences.js'

/**
 * @typedef {Object} UseSpeechSynthesisOptions
 * @property {() => void} [onStart] 开始朗读
 * @property {() => void} [onEnd] 朗读结束（正常结束或出错）
 * @property {() => void} [onBoundary] 朗读到词边界时触发，可用于口型同步节奏
 */

/**
 * @param {UseSpeechSynthesisOptions} [options]
 */
export function useSpeechSynthesis(options = {}) {
  const supported = ref(typeof window !== 'undefined' && 'speechSynthesis' in window)
  /** 是否正在朗读 */
  const speaking = ref(false)
  /** @type {import('vue').Ref<SpeechSynthesisVoice[]>} */
  const voices = ref([])
  const voiceName = ref('')

  // 开关与语速来自全局偏好（已持久化）
  const enabled = voiceEnabled
  const rate = voiceRate

  /**
   * 优先挑中文音色
   * @param {SpeechSynthesisVoice[]} list
   * @returns {SpeechSynthesisVoice | null}
   */
  function pickVoice(list) {
    if (list.length === 0) return null
    return (
      list.find((v) => /^zh[-_]?(CN|Hans)/i.test(v.lang)) ??
      list.find((v) => /^zh/i.test(v.lang)) ??
      list[0]
    )
  }

  function loadVoices() {
    if (!supported.value) return
    const list = window.speechSynthesis.getVoices()
    if (list.length === 0) return // 部分浏览器首次为空，等 voiceschanged 再取
    voices.value = list
    voiceName.value = pickVoice(list)?.name ?? ''
  }

  /** @param {number} value */
  function setRate(value) {
    rate.value = value
  }

  /** @param {boolean} value */
  function setEnabled(value) {
    enabled.value = value
    if (!value) cancel()
  }

  /**
   * 朗读文本
   * @param {string} text
   */
  function speak(text) {
    if (!supported.value || !enabled.value || !text.trim()) return

    cancel()

    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = 'zh-CN'
    utterance.rate = rate.value

    const voice = voices.value.find((v) => v.name === voiceName.value)
    if (voice) utterance.voice = voice

    utterance.onstart = () => {
      speaking.value = true
      options.onStart?.()
    }
    utterance.onboundary = () => {
      options.onBoundary?.()
    }
    utterance.onend = () => {
      speaking.value = false
      options.onEnd?.()
    }
    utterance.onerror = () => {
      speaking.value = false
      options.onEnd?.()
    }

    window.speechSynthesis.speak(utterance)
  }

  /** 停止朗读 */
  function cancel() {
    if (!supported.value) return
    window.speechSynthesis.cancel()
    speaking.value = false
  }

  onMounted(() => {
    loadVoices()
    // Chrome 首次 getVoices() 返回空数组，需要监听 voiceschanged
    window.speechSynthesis?.addEventListener?.('voiceschanged', loadVoices)
  })

  onBeforeUnmount(() => {
    cancel()
    window.speechSynthesis?.removeEventListener?.('voiceschanged', loadVoices)
  })

  return {
    supported,
    enabled,
    speaking,
    rate,
    voices,
    voiceName,
    speak,
    cancel,
    setRate,
    setEnabled,
  }
}
