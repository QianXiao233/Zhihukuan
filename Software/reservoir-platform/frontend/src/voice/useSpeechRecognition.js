/**
 * 录音识别 hook：点击开始录音 → 再次点击结束 → 上传 /api/asr → 返回文字
 * 识别结果交给调用方填入输入框，由用户确认后再发送。
 */
import { onBeforeUnmount, ref, shallowRef } from 'vue'
import { AudioRecorder } from './AudioRecorder.js'
import { recognizeSpeech } from '../api/chat.js'

/**
 * @typedef {Object} UseSpeechRecognitionOptions
 * @property {(text: string) => void} onResult 识别成功回调
 * @property {number} [targetSampleRate] 目标采样率，默认 16000
 */

/**
 * @param {UseSpeechRecognitionOptions} options
 */
export function useSpeechRecognition(options) {
  const supported = ref(AudioRecorder.isSupported())
  const recording = ref(false)
  /** 上传识别中 */
  const busy = ref(false)
  const error = ref('')

  const recorder = shallowRef(new AudioRecorder({ targetSampleRate: options.targetSampleRate }))

  async function start() {
    error.value = ''
    try {
      await recorder.value.start()
      recording.value = true
    } catch (e) {
      error.value = e instanceof Error ? e.message : '无法访问麦克风，请检查权限设置'
    }
  }

  async function stop() {
    if (!recording.value) return
    recording.value = false
    busy.value = true

    try {
      const wav = await recorder.value.stop()
      const text = await recognizeSpeech(wav)
      if (text.trim()) {
        options.onResult(text.trim())
      } else {
        error.value = '没有识别到语音内容，请靠近麦克风重试'
      }
    } catch (e) {
      error.value = e instanceof Error ? e.message : '语音识别失败，请稍后重试'
    } finally {
      busy.value = false
    }
  }

  /** 切换录音状态 */
  async function toggle() {
    if (recording.value) await stop()
    else await start()
  }

  onBeforeUnmount(() => {
    recorder.value.dispose()
  })

  return { supported, recording, busy, error, start, stop, toggle }
}
