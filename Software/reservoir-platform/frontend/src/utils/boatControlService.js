const DEFAULT_HTTP_URL = 'http://127.0.0.1:4174'
const DEFAULT_WS_URL = 'ws://127.0.0.1:4174'

function httpUrl() {
  return import.meta.env.VITE_BOAT_CONTROL_HTTP_URL || DEFAULT_HTTP_URL
}

function wsUrl() {
  return import.meta.env.VITE_BOAT_CONTROL_WS_URL || DEFAULT_WS_URL
}

/**
 * 无人艇控制桥接服务客户端。
 *
 * 这里明确区分无人艇链路和水库 RTU：
 *   浏览器 -> 本地 WebSocket -> serial-service -> 串口 115200 -> ESP-NOW -> 船端
 * 页面不订阅、不发布 MQTT，也不把闸门指令混入无人艇控制。
 */
export class BoatControlService {
  constructor({ onMessage, onStatus } = {}) {
    this.socket = null
    this.onMessage = onMessage
    this.onStatus = onStatus
  }

  async listPorts() {
    const response = await fetch(`${httpUrl()}/api/ports`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.error || '无法读取串口列表')
    return Array.isArray(data) ? data : []
  }

  async connectSerial(port) {
    const response = await fetch(`${httpUrl()}/api/connect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ port }),
    })
    const data = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(data.error || '串口连接失败')
    return data
  }

  async disconnectSerial() {
    await fetch(`${httpUrl()}/api/disconnect`, { method: 'POST' }).catch(() => {})
  }

  connect() {
    if (this.socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this.socket.readyState)) return
    const socket = new WebSocket(wsUrl())
    this.socket = socket
    this.onStatus?.('connecting')
    socket.onopen = () => this.onStatus?.('open')
    socket.onmessage = (event) => {
      try {
        this.onMessage?.(JSON.parse(event.data))
      } catch {
        this.onMessage?.({ type: 'error', message: '无人艇服务返回了无法解析的数据' })
      }
    }
    socket.onerror = () => this.onStatus?.('error')
    socket.onclose = () => {
      if (this.socket === socket) this.socket = null
      this.onStatus?.('closed')
    }
  }

  sendCommand(command) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'command', ...command }))
    return true
  }

  release() {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'release' }))
    return true
  }

  close() {
    this.socket?.close()
    this.socket = null
  }
}

export { DEFAULT_HTTP_URL, DEFAULT_WS_URL }
