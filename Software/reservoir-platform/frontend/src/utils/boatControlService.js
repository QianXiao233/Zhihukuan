const DEFAULT_HTTP_URL = 'http://127.0.0.1:4174'
const DEFAULT_WS_URL = 'ws://127.0.0.1:4174'
// 断线自动重连退避：1.5s 起步，最多 5s
const RECONNECT_BASE_MS = 1500
const RECONNECT_MAX_MS = 5000

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
    this.reconnectTimer = null
    this.reconnectDelay = RECONNECT_BASE_MS
    this.closedByUser = false
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
    this.closedByUser = false
    const socket = new WebSocket(wsUrl())
    this.socket = socket
    this.onStatus?.('connecting')
    socket.onopen = () => {
      this.reconnectDelay = RECONNECT_BASE_MS
      this.onStatus?.('open')
    }
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
      // 自动重连：本地服务重启/网络抖动后不用刷新页面。
      // 退避 1.5s -> 3s -> 5s 封顶，避免服务没起时疯狂重试。
      if (!this.closedByUser && !this.reconnectTimer) {
        this.reconnectTimer = window.setTimeout(() => {
          this.reconnectTimer = null
          this.connect()
        }, this.reconnectDelay)
        this.reconnectDelay = Math.min(this.reconnectDelay + 1000, RECONNECT_MAX_MS)
      }
    }
  }

  sendCommand(command) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'command', ...command }))
    return true
  }

  /**
   * 视觉接管闸门。allow=false 时服务端会屏蔽 locator.py 的坐标，
   * 网页的停止/急停重新拥有最高优先级（释放动作除外）。
   */
  sendVisionGate(allow) {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'visionGate', allow: Boolean(allow) }))
    return true
  }

  release() {
    if (this.socket?.readyState !== WebSocket.OPEN) return false
    this.socket.send(JSON.stringify({ type: 'release' }))
    return true
  }

  close() {
    this.closedByUser = true
    window.clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.socket?.close()
    this.socket = null
  }
}

export { DEFAULT_HTTP_URL, DEFAULT_WS_URL }
