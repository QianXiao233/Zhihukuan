/**
 * 录音 + 转 WAV 16kHz 单声道
 *
 * 链路：浏览器 MediaRecorder 采集 → decodeAudioData 解码 → 重采样到 16kHz
 * → 编码为 16bit PCM 单声道 WAV，交给后端 /api/asr（FunASR Paraformer-zh）。
 */

/** ASR 侧要求的采样率 */
export const TARGET_SAMPLE_RATE = 16000

/**
 * @typedef {Object} AudioRecorderOptions
 * @property {number} [targetSampleRate] 目标采样率，默认 16000
 */

/**
 * 挑选浏览器支持的录音容器
 * @returns {string | undefined}
 */
function pickMimeType() {
  if (typeof MediaRecorder === 'undefined' || typeof MediaRecorder.isTypeSupported !== 'function') {
    return undefined
  }
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4']
  return candidates.find((type) => MediaRecorder.isTypeSupported(type))
}

/**
 * Float32 [-1,1] → 16bit PCM
 * @param {DataView} view
 * @param {number} offset
 * @param {Float32Array} samples
 */
function floatTo16BitPCM(view, offset, samples) {
  for (let i = 0; i < samples.length; i += 1) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
}

/**
 * @param {DataView} view
 * @param {number} offset
 * @param {string} text
 */
function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i += 1) {
    view.setUint8(offset + i, text.charCodeAt(i))
  }
}

/**
 * 编码为 WAV（16bit / 单声道 / 指定采样率）
 * @param {Float32Array} samples
 * @param {number} sampleRate
 * @returns {Blob}
 */
export function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  writeAscii(view, 0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeAscii(view, 8, 'WAVE')

  writeAscii(view, 12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 块长度
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // 单声道
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 字节率
  view.setUint16(32, 2, true) // 块对齐
  view.setUint16(34, 16, true) // 位深

  writeAscii(view, 36, 'data')
  view.setUint32(40, samples.length * 2, true)
  floatTo16BitPCM(view, 44, samples)

  return new Blob([view], { type: 'audio/wav' })
}

/**
 * 线性插值重采样
 * @param {Float32Array} input
 * @param {number} inputRate
 * @param {number} outputRate
 * @returns {Float32Array}
 */
export function resample(input, inputRate, outputRate) {
  if (inputRate === outputRate || input.length === 0) return input

  const ratio = inputRate / outputRate
  const length = Math.max(1, Math.floor(input.length / ratio))
  const output = new Float32Array(length)

  for (let i = 0; i < length; i += 1) {
    const pos = i * ratio
    const index = Math.floor(pos)
    const frac = pos - index
    const a = input[index] ?? 0
    const b = input[index + 1] ?? a
    output[i] = a + (b - a) * frac
  }
  return output
}

/**
 * 多声道混合为单声道
 * @param {AudioBuffer} buffer
 * @returns {Float32Array}
 */
function toMono(buffer) {
  if (buffer.numberOfChannels === 1) return buffer.getChannelData(0)

  const length = buffer.length
  const mono = new Float32Array(length)
  for (let ch = 0; ch < buffer.numberOfChannels; ch += 1) {
    const data = buffer.getChannelData(ch)
    for (let i = 0; i < length; i += 1) mono[i] += data[i]
  }
  for (let i = 0; i < length; i += 1) mono[i] /= buffer.numberOfChannels
  return mono
}

export class AudioRecorder {
  /** @type {MediaStream | null} */
  #stream = null
  /** @type {MediaRecorder | null} */
  #recorder = null
  /** @type {Blob[]} */
  #chunks = []
  /** @type {number} */
  #targetSampleRate
  /** @type {boolean} */
  #active = false

  /** @param {AudioRecorderOptions} [options] */
  constructor(options = {}) {
    this.#targetSampleRate = options.targetSampleRate ?? TARGET_SAMPLE_RATE
  }

  /**
   * 浏览器是否具备录音能力
   * @returns {boolean}
   */
  static isSupported() {
    return (
      typeof navigator !== 'undefined' &&
      !!navigator.mediaDevices &&
      typeof navigator.mediaDevices.getUserMedia === 'function' &&
      typeof MediaRecorder !== 'undefined'
    )
  }

  /** @returns {boolean} */
  get isRecording() {
    return this.#active
  }

  /**
   * 开始录音
   * @returns {Promise<void>}
   */
  async start() {
    if (this.#active) return
    if (!AudioRecorder.isSupported()) {
      throw new Error('当前浏览器不支持录音，请使用 Chrome / Edge')
    }

    this.#stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      },
    })

    const mimeType = pickMimeType()
    this.#recorder = mimeType
      ? new MediaRecorder(this.#stream, { mimeType })
      : new MediaRecorder(this.#stream)
    this.#chunks = []

    this.#recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) this.#chunks.push(e.data)
    }

    this.#recorder.start()
    this.#active = true
  }

  /**
   * 结束录音并返回 16kHz 单声道 WAV
   * @returns {Promise<Blob>}
   */
  async stop() {
    if (!this.#active || !this.#recorder) {
      throw new Error('当前没有进行中的录音')
    }

    const recorder = this.#recorder

    /** @type {Blob} */
    const recorded = await new Promise((resolve) => {
      recorder.onstop = () => {
        resolve(new Blob(this.#chunks, { type: recorder.mimeType || 'audio/webm' }))
      }
      recorder.stop()
    })

    this.#active = false
    this.#releaseStream()

    return this.#toWav(recorded)
  }

  /** 取消录音（丢弃数据） */
  cancel() {
    try {
      if (this.#recorder && this.#active) this.#recorder.stop()
    } catch {
      // 忽略停止异常
    }
    this.#active = false
    this.#chunks = []
    this.#releaseStream()
  }

  /** 释放麦克风 */
  #releaseStream() {
    this.#stream?.getTracks().forEach((track) => track.stop())
    this.#stream = null
    this.#recorder = null
  }

  /**
   * 解码 → 单声道 → 重采样 16kHz → WAV
   * @param {Blob} blob
   * @returns {Promise<Blob>}
   */
  async #toWav(blob) {
    const arrayBuffer = await blob.arrayBuffer()
    const AudioCtx = window.AudioContext ?? window.webkitAudioContext
    const audioContext = new AudioCtx()

    try {
      const decoded = await audioContext.decodeAudioData(arrayBuffer.slice(0))
      const mono = toMono(decoded)
      const pcm = resample(mono, decoded.sampleRate, this.#targetSampleRate)
      return encodeWav(pcm, this.#targetSampleRate)
    } finally {
      void audioContext.close()
    }
  }

  /** 释放资源（组件卸载时调用） */
  dispose() {
    this.cancel()
  }
}
