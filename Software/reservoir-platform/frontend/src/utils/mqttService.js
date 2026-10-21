import mqtt from 'mqtt'

/**
 * MQTT over WebSocket client for reservoir RTU/水工设备数据。
 * 无人艇不使用这里的 MQTT：无人艇走 serial-service 的 WebSocket + 串口 + ESP-NOW 链路。
 */
export class MqttService {
  constructor(brokerUrl, options = {}) {
    this.brokerUrl = brokerUrl
    this.client = null
    this.handlers = []
    this.statusHandlers = []
    this.pendingSubscriptions = []
    this.options = { reconnectPeriod: 4000, connectTimeout: 30000, clean: true, ...options }
  }

  connect() {
    if (this.client || !this.brokerUrl) return
    try {
      this.client = mqtt.connect(this.brokerUrl, this.options)
      this.notifyStatus('connecting')
      this.client.on('connect', () => {
        this.notifyStatus('connected')
        while (this.pendingSubscriptions.length) {
          const item = this.pendingSubscriptions.shift()
          this.client.subscribe(item.topic, item.options, item.callback)
        }
      })
      this.client.on('reconnect', () => this.notifyStatus('reconnecting'))
      this.client.on('message', (topic, payload) => {
        let data = payload.toString()
        try { data = JSON.parse(data) } catch { /* 保留字符串消息 */ }
        this.handlers.forEach((handler) => handler(topic, data))
      })
      this.client.on('error', (error) => {
        console.warn('[MQTT] connection error', error.message)
        this.notifyStatus('error', error)
      })
      this.client.on('close', () => this.notifyStatus('disconnected'))
      this.client.on('offline', () => this.notifyStatus('offline'))
    } catch (error) {
      console.warn('[MQTT] unable to create client', error)
      this.notifyStatus('error')
      this.client = null
    }
  }

  subscribe(topic, options = { qos: 0 }, callback) {
    const done = typeof callback === 'function' ? callback : () => {}
    if (this.client?.connected) this.client.subscribe(topic, options, done)
    else this.pendingSubscriptions.push({ topic, options, callback: done })
  }

  publish(topic, message, options = { qos: 1 }, callback) {
    if (!this.client?.connected) return false
    const payload = typeof message === 'string' ? message : JSON.stringify(message)
    this.client.publish(topic, payload, options, callback)
    return true
  }

  onMessage(handler) {
    if (typeof handler === 'function') this.handlers.push(handler)
  }

  onStatus(handler) {
    if (typeof handler === 'function') this.statusHandlers.push(handler)
  }

  disconnect() {
    this.pendingSubscriptions = []
    this.handlers = []
    this.statusHandlers = []
    if (this.client) this.client.end(false)
    this.client = null
  }

  notifyStatus(status) {
    this.statusHandlers.forEach((handler) => handler(status))
  }
}

export function mqttUrl() {
  const configured = import.meta.env.VITE_MQTT_BROKER_URL || 'ws://81.70.63.53:8083/mqtt'
  try {
    const parsed = new URL(configured)
    const endpoint = parsed.pathname && parsed.pathname !== '/' ? parsed.pathname : '/mqtt'
    return `${parsed.protocol}//${parsed.host}${endpoint}`
  } catch {
    return configured.endsWith('/mqtt') ? configured : `${configured.replace(/\/$/, '')}/mqtt`
  }
}

export function mqttOptions() {
  const options = {
    clean: true,
    connectTimeout: 30 * 1000,
    reconnectPeriod: 4000,
    clientId: import.meta.env.VITE_MQTT_CLIENT_ID || `reservoir_vue_${Math.random().toString(16).slice(2, 8)}`,
  }
  const username = import.meta.env.VITE_MQTT_USERNAME
  const password = import.meta.env.VITE_MQTT_PASSWORD
  if (username) options.username = username
  if (password) options.password = password
  return options
}
