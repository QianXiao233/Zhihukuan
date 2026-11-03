/* global mqtt */
(() => {
  'use strict'

  const STORAGE_KEY = 'zhka.stm32.simulator.v1'
  const DEFAULT_BROKER = 'wss://platform.zhka.qianxiao.xin/mqtt'
  const MAX_LOG = 300

  const METRICS = [
    {
      key: 'level', label: '水位', code: 'level', unit: 'm', digits: 2,
      min: 0, max: 5, step: 0.01, value: 0.85, amp: 0.04,
      low: 0.2, high: 1.2, threshold: '阈值 0.20 ~ 1.20 m',
    },
    {
      key: 'temp', label: '液温', code: 'temp', unit: '℃', digits: 1,
      min: 0, max: 45, step: 0.1, value: 22.5, amp: 0.35,
      low: 5, high: 35, threshold: '阈值 5.0 ~ 35.0 ℃',
    },
    {
      key: 'ph', label: 'pH', code: 'ph', unit: '', digits: 2,
      min: 0, max: 14, step: 0.01, value: 7.2, amp: 0.06,
      low: 6.5, high: 8.5, threshold: '阈值 6.50 ~ 8.50',
    },
    {
      key: 'orp', label: 'ORP', code: 'orp', unit: 'mV', digits: 0,
      min: -500, max: 500, step: 1, value: 120, amp: 5,
      low: -100, high: 300, threshold: '阈值 -100 ~ 300 mV',
    },
  ]

  const PRESETS = {
    normal: { name: '正常水情', level: 0.85, temp: 22.5, ph: 7.2, orp: 120, gates: [0, 0, 0, 0, 0, 0] },
    flood: { name: '超汛限水位', level: 1.62, temp: 24.2, ph: 7.1, orp: 115, gates: [1, 1, 0, 0, 0, 0] },
    water: { name: '水质异常', level: 0.92, temp: 37.5, ph: 5.7, orp: -180, gates: [0, 0, 0, 0, 0, 0] },
    allopen: { name: '六闸全开', gates: [1, 1, 1, 1, 1, 1] },
    allclose: { name: '六闸全关', gates: [0, 0, 0, 0, 0, 0] },
  }

  const $ = (id) => document.getElementById(id)
  const num = (value, digits = 2) => Number(Number(value).toFixed(digits))
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value))
  const pad = (value) => String(value).padStart(2, '0')
  const nowTime = () => {
    const d = new Date()
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  }
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

  const state = {
    client: null,
    connected: false,
    connecting: false,
    manuallyClosed: false,
    autoReport: true,
    drift: true,
    interval: 2000,
    tx: 0,
    rx: 0,
    connectedAt: 0,
    lastStatusAt: 0,
    gates: [0, 0, 0, 0, 0, 0],
    logPaused: false,
    warnedProduction: false,
    reportTimer: null,
    uiTimer: null,
    driftTimer: null,
    publishDebounce: null,
    driftT: Math.random() * 10,
    connectWatch: null,
  }

  const sensorEls = new Map()
  let gateEls = []

  function init() {
    loadConfig()
    renderSensors()
    renderGates()
    renderPreview()
    bindEvents()
    updateConnectionUI('offline')
    updateBrokerNotice()
    updateGateChip()
    updateStats()

    state.uiTimer = window.setInterval(updateStats, 1000)
    state.driftTimer = window.setInterval(driftTick, 900)
    window.addEventListener('beforeunload', () => {
      try { state.client?.end(true) } catch { /* ignore */ }
    })
  }

  // ─────────── 配置持久化 ───────────

  function randomClientId() {
    return `stm32-sim-${Math.random().toString(16).slice(2, 8)}`
  }

  function defaultConfig() {
    return {
      broker: DEFAULT_BROKER,
      clientId: randomClientId(),
      statusTopic: 'rtu/status',
      controlTopic: 'rtu/control',
      interval: 2000,
      username: '',
    }
  }

  function loadConfig() {
    let config = defaultConfig()
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (raw) config = { ...config, ...JSON.parse(raw) }
    } catch { /* localStorage 不可用时使用默认值 */ }

    $('broker').value = config.broker || DEFAULT_BROKER
    // Client ID 每次打开重新生成，避免同时开多个调试页时互相顶掉连接。
    $('clientId').value = randomClientId()
    $('statusTopic').value = config.statusTopic || 'rtu/status'
    $('controlTopic').value = config.controlTopic || 'rtu/control'
    $('interval').value = String(config.interval || 2000)
    $('username').value = config.username || ''
    state.interval = Number(config.interval) || 2000
  }

  function saveConfig() {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({
        broker: $('broker').value.trim(),
        clientId: $('clientId').value.trim(),
        statusTopic: $('statusTopic').value.trim(),
        controlTopic: $('controlTopic').value.trim(),
        interval: Number($('interval').value) || 2000,
        username: $('username').value.trim(),
      }))
    } catch { /* 忽略本地存储异常 */ }
  }

  function readConfig() {
    return {
      broker: $('broker').value.trim(),
      clientId: $('clientId').value.trim(),
      statusTopic: $('statusTopic').value.trim(),
      controlTopic: $('controlTopic').value.trim(),
      interval: clamp(Number($('interval').value) || 2000, 500, 60000),
      username: $('username').value.trim(),
      password: $('password').value,
    }
  }

  // ─────────── 传感器 ───────────

  function renderSensors() {
    const root = $('sensors')
    root.innerHTML = ''
    METRICS.forEach((metric) => {
      const row = document.createElement('div')
      row.className = 'sensor'
      row.innerHTML = `
        <div class="sensor__name">
          <strong>${metric.label}</strong>
          <small>${metric.code}</small>
        </div>
        <input class="sensor__range" type="range" min="${metric.min}" max="${metric.max}" step="${metric.step}" aria-label="${metric.label}滑杆" />
        <input class="sensor__value" type="number" min="${metric.min}" max="${metric.max}" step="${metric.step}" aria-label="${metric.label}数值" />
        <span class="sensor__unit">${metric.unit || '—'}</span>
        <small class="sensor__threshold">${metric.threshold}</small>
      `
      const range = row.querySelector('.sensor__range')
      const value = row.querySelector('.sensor__value')
      metric.value = clamp(metric.value, metric.min, metric.max)
      metric.base = metric.value
      range.value = String(metric.value)
      value.value = metric.value.toFixed(metric.digits)
      range.addEventListener('input', () => setMetric(metric.key, Number(range.value)))
      value.addEventListener('change', () => setMetric(metric.key, Number(value.value)))
      sensorEls.set(metric.key, { row, range, value })
      root.appendChild(row)
    })
    syncSensorUI()
  }

  function getMetric(key) {
    return METRICS.find((item) => item.key === key)
  }

  function setMetric(key, value) {
    const metric = getMetric(key)
    if (!metric) return
    if (!Number.isFinite(Number(value))) return
    metric.value = num(clamp(Number(value), metric.min, metric.max), metric.digits)
    metric.base = metric.value
    syncSensorUI()
    renderPreview()
    schedulePublish()
  }

  function syncSensorUI() {
    METRICS.forEach((metric) => {
      const el = sensorEls.get(metric.key)
      if (!el) return
      el.range.value = String(metric.value)
      if (document.activeElement !== el.value) el.value.value = metric.value.toFixed(metric.digits)
      const alarm = metric.low != null && metric.high != null
        ? metric.value < metric.low || metric.value > metric.high
        : false
      el.row.classList.toggle('is-alarm', alarm)
    })
  }

  function driftTick() {
    if (!state.drift) return
    state.driftT += 0.22
    METRICS.forEach((metric, index) => {
      if (!Number.isFinite(metric.base)) metric.base = metric.value
      const wave = Math.sin(state.driftT * (0.55 + index * 0.06) + index * 1.7)
      const noise = (Math.random() - 0.5) * metric.amp * 0.45
      metric.value = num(clamp(metric.base + wave * metric.amp + noise, metric.min, metric.max), metric.digits)
    })
    syncSensorUI()
    renderPreview()
  }

  // ─────────── 闸门 ───────────

  function renderGates() {
    const root = $('gates')
    root.innerHTML = ''
    gateEls = []
    state.gates.forEach((_, index) => {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'gate'
      button.dataset.gate = String(index + 1)
      button.innerHTML = `
        <span class="gate__num">${pad(index + 1)}</span>
        <span class="gate__info"><strong>${index + 1} 号闸门</strong><small>关闭</small></span>
        <span class="gate__switch"><i></i></span>
      `
      button.addEventListener('click', () => {
        const value = state.gates[index] === 1 ? 0 : 1
        state.gates[index] = value
        syncGateUI()
        log('sys', 'manual', `手动拨动 ${index + 1} 号闸门 → ${value ? '开' : '关'}`)
        if (state.connected) publishStatus('手动闸门操作')
      })
      gateEls.push(button)
      root.appendChild(button)
    })
    syncGateUI()
  }

  function syncGateUI() {
    gateEls.forEach((button, index) => {
      const open = state.gates[index] === 1
      button.classList.toggle('is-open', open)
      button.setAttribute('aria-pressed', open ? 'true' : 'false')
      const text = button.querySelector('.gate__info small')
      if (text) text.textContent = open ? '开启' : '关闭'
    })
    updateGateChip()
    renderPreview()
  }

  function updateGateChip() {
    const open = state.gates.filter((value) => value === 1).length
    $('gateChip').textContent = `${open} / 6 开启`
  }

  function applyGate(index, value, source) {
    if (index < 0 || index > 5) return false
    state.gates[index] = value
    syncGateUI()
    log('sys', 'relay', `${source}：${index + 1} 号闸门 → ${value ? '开' : '关'}`)
    if (state.connected) {
      window.setTimeout(() => publishStatus(`控制应答 relay #${index + 1}`), 320)
    }
    return true
  }

  function setAllGates(value, source) {
    state.gates = state.gates.map(() => value)
    syncGateUI()
    log('sys', 'relay', `${source}：全部闸门 → ${value ? '开' : '关'}`)
    if (state.connected) {
      window.setTimeout(() => publishStatus('控制应答 relay.all'), 320)
    }
  }

  // ─────────── 报文 ───────────

  function buildStatus() {
    const payload = {}
    METRICS.forEach((metric) => {
      payload[metric.key] = num(metric.value, metric.digits)
    })
    payload.relay = state.gates.slice()
    return payload
  }

  function buildHeartbeat() {
    return {
      level: null,
      temp: null,
      ph: null,
      orp: null,
      relay: state.gates.slice(),
    }
  }

  function formatPayload(payload) {
    const lines = Object.entries(payload).map(([key, value]) => {
      const formatted = Array.isArray(value) ? `[${value.join(', ')}]` : JSON.stringify(value)
      return `  "${key}": ${formatted}`
    })
    return `{\n${lines.join(',\n')}\n}`
  }

  function renderPreview(payload = buildStatus(), label = '') {
    const text = formatPayload(payload)
    $('statusPreview').textContent = text
    const bytes = new TextEncoder().encode(JSON.stringify(payload)).length
    $('payloadMeta').textContent = label
      ? `${label} · ${bytes} 字节`
      : `${bytes} 字节 · 点击「立即上报」发送`
  }

  function publishStatus(reason = '手动上报') {
    const payload = buildStatus()
    return publishPayload(payload, reason)
  }

  function publishPayload(payload, reason) {
    renderPreview(payload, reason)
    const config = readConfig()
    if (!state.connected || !state.client) {
      log('err', config.statusTopic, payload, '未连接，未发送')
      return false
    }
    const body = JSON.stringify(payload)
    state.client.publish(config.statusTopic, body, { qos: 0, retain: false }, (error) => {
      if (error) log('err', config.statusTopic, body, `发布失败：${error.message}`)
    })
    state.tx += 1
    state.lastStatusAt = Date.now()
    log('tx', config.statusTopic, payload, reason)
    updateStats()
    return true
  }

  function schedulePublish() {
    if (!state.connected || !state.autoReport) return
    if (state.publishDebounce) window.clearTimeout(state.publishDebounce)
    state.publishDebounce = window.setTimeout(() => publishStatus('传感器变化'), 260)
  }

  function publishHeartbeat() {
    publishPayload(buildHeartbeat(), '空帧心跳')
  }

  // ─────────── 控制协议 ───────────

  function normalizeState(value) {
    if (value === 1 || value === '1' || value === true) return 1
    if (value === 0 || value === '0' || value === false) return 0
    if (typeof value === 'string') {
      const text = value.trim().toLowerCase()
      if (['open', 'on', 'true', '1'].includes(text)) return 1
      if (['close', 'closed', 'off', 'false', '0'].includes(text)) return 0
    }
    return null
  }

  function handleControl(data, source = '平台') {
    if (!data || typeof data !== 'object') {
      log('err', 'control', String(data), `${source}：控制报文不是 JSON 对象`)
      return false
    }
    const cmd = String(data.cmd || '').toLowerCase()
    if (cmd === 'relay.set') {
      const index = Number(data.relay) - 1
      const value = normalizeState(data.state)
      if (!Number.isInteger(index) || index < 0 || index > 5 || value == null) {
        log('err', 'control', data, `${source}：relay.set 参数无效`)
        return false
      }
      return applyGate(index, value, source)
    }
    if (cmd === 'relay.all') {
      const value = normalizeState(data.state)
      if (value == null) {
        log('err', 'control', data, `${source}：relay.all 缺少有效 state`)
        return false
      }
      setAllGates(value, source)
      return true
    }
    log('err', 'control', data, `${source}：不支持的控制命令 ${cmd || '(空)'}`)
    return false
  }

  function injectControl() {
    const raw = $('rawControl').value.trim()
    if (!raw) {
      log('err', 'local', '', '控制报文为空')
      return
    }
    let data
    try {
      data = JSON.parse(raw)
    } catch (error) {
      log('err', 'local', raw, `JSON 解析失败：${error.message}`)
      return
    }
    log('rx', 'local', data, '本地注入')
    handleControl(data, '本地注入')
  }

  function loopback() {
    if (!state.connected || !state.client) {
      log('err', 'control', '', '未连接，无法执行回环测试')
      return
    }
    const raw = $('rawControl').value.trim()
    try {
      JSON.parse(raw)
    } catch (error) {
      log('err', 'control', raw, `JSON 解析失败：${error.message}`)
      return
    }
    const config = readConfig()
    state.client.publish(config.controlTopic, raw, { qos: 2 }, (error) => {
      if (error) log('err', config.controlTopic, raw, `回环发布失败：${error.message}`)
      else log('sys', config.controlTopic, raw, '回环测试已发布，等待订阅返回')
    })
  }

  // ─────────── MQTT ───────────

  function isLocalBroker(url) {
    try {
      const host = new URL(url).hostname
      return host === 'localhost'
        || host === '127.0.0.1'
        || host === '::1'
        || host === '[::1]'
        || /^10\./.test(host)
        || /^192\.168\./.test(host)
        || /^172\.(1[6-9]|2\d|3[01])\./.test(host)
    } catch {
      return false
    }
  }

  function updateBrokerNotice() {
    const broker = $('broker').value.trim()
    const local = isLocalBroker(broker)
    $('brokerNotice').hidden = local
    $('brokerChip').textContent = local ? '本地 Broker' : '线上 Broker'
    $('brokerChip').classList.toggle('chip--muted', local)
  }

  function updateConnectionUI(status) {
    const pill = $('connPill')
    const text = $('connText')
    const connectBtn = $('connectBtn')
    const disconnectBtn = $('disconnectBtn')
    const labels = {
      offline: ['offline', '未连接'],
      connecting: ['connecting', '连接中…'],
      online: ['online', '在线'],
      error: ['error', '连接异常'],
    }
    const [kind, label] = labels[status] || labels.offline
    pill.dataset.state = kind
    text.textContent = label
    $('statLink').textContent = label
    connectBtn.hidden = status === 'online' || status === 'connecting'
    disconnectBtn.hidden = status === 'offline' || status === 'error'
    connectBtn.disabled = status === 'connecting'
    connectBtn.textContent = status === 'connecting' ? '连接中…' : '连接 Broker'
    $('connectBtn').classList.toggle('btn--primary', status !== 'connecting')
  }

  function connect() {
    if (state.connecting || state.connected) return
    if (typeof mqtt === 'undefined' || !mqtt.connect) {
      log('err', 'system', '', 'mqtt.js 未加载，请确认 vendor/mqtt.min.js 存在')
      updateConnectionUI('error')
      return
    }
    const config = readConfig()
    if (!/^wss?:\/\//i.test(config.broker)) {
      log('err', 'system', config.broker, 'Broker 必须以 ws:// 或 wss:// 开头')
      updateConnectionUI('error')
      return
    }
    state.interval = config.interval
    if (!config.clientId) {
      log('err', 'system', '', 'Client ID 不能为空')
      updateConnectionUI('error')
      return
    }
    if (!isLocalBroker(config.broker) && !state.warnedProduction) {
      const confirmed = window.confirm(
        '当前 Broker 不是本机/内网地址。\n\n继续连接后，模拟数据会写入线上平台，可能触发真实告警、通知和落库记录。\n\n确认继续吗？',
      )
      if (!confirmed) return
      state.warnedProduction = true
    }

    saveConfig()
    if (state.client) {
      try { state.client.end(true) } catch { /* ignore */ }
      state.client = null
      state.connected = false
    }
    state.manuallyClosed = false
    state.connecting = true
    updateConnectionUI('connecting')
    log('sys', 'system', config.broker, `正在连接（Client ID: ${config.clientId}）`)

    try {
      const options = {
        clientId: config.clientId,
        clean: true,
        reconnectPeriod: 0,
        connectTimeout: 10000,
        keepalive: 30,
      }
      if (config.username) options.username = config.username
      if (config.password) options.password = config.password
      const client = mqtt.connect(config.broker, options)
      state.client = client

      if (state.connectWatch) window.clearTimeout(state.connectWatch)
      state.connectWatch = window.setTimeout(() => {
        if (state.connecting && !state.connected) {
          state.connecting = false
          updateConnectionUI('error')
          log('err', 'system', config.broker, '连接超时（10 秒），请检查地址、端口和网络')
          try { client.end(true) } catch { /* ignore */ }
          state.client = null
        }
      }, 12000)

      client.on('connect', () => {
        if (state.client !== client) return
        if (state.connectWatch) window.clearTimeout(state.connectWatch)
        state.connectWatch = null
        state.connecting = false
        state.connected = true
        state.connectedAt = Date.now()
        updateConnectionUI('online')
        log('sys', 'system', config.broker, `已连接，Client ID: ${config.clientId}`)

        client.subscribe(config.controlTopic, { qos: 2 }, (error) => {
          if (error) {
            log('err', config.controlTopic, '', `订阅失败：${error.message}`)
          } else {
            log('sys', config.controlTopic, '', '已订阅控制主题 QoS 2')
          }
        })
        startReportTimer()
        window.setTimeout(() => publishStatus('连接后首帧'), 180)
      })

      client.on('message', (topic, payload) => {
        if (state.client !== client) return
        if (topic !== readConfig().controlTopic) return
        state.rx += 1
        updateStats()
        let data
        const text = payload.toString()
        try {
          data = JSON.parse(text)
        } catch {
          log('err', topic, text, '收到非 JSON 控制报文')
          return
        }
        log('rx', topic, data, '平台控制')
        handleControl(data, '平台')
      })

      client.on('error', (error) => {
        if (state.client !== client) return
        state.connecting = false
        log('err', 'system', '', `MQTT 错误：${error.message}`)
        if (!state.connected) updateConnectionUI('error')
      })

      client.on('close', () => {
        if (state.client !== client) return
        const wasManual = state.manuallyClosed
        state.connected = false
        state.connecting = false
        state.client = null
        stopReportTimer()
        updateConnectionUI(wasManual ? 'offline' : 'error')
        if (!wasManual) log('err', 'system', '', '连接已断开')
      })

      client.on('offline', () => {
        if (state.client !== client) return
        log('sys', 'system', '', '客户端进入离线状态')
      })
    } catch (error) {
      state.connecting = false
      state.client = null
      updateConnectionUI('error')
      log('err', 'system', '', `创建客户端失败：${error.message}`)
    }
  }

  function disconnect() {
    state.manuallyClosed = true
    stopReportTimer()
    if (state.connectWatch) window.clearTimeout(state.connectWatch)
    state.connectWatch = null
    const client = state.client
    state.client = null
    state.connected = false
    state.connecting = false
    if (client) {
      try { client.end(true) } catch { /* ignore */ }
    }
    updateConnectionUI('offline')
    log('sys', 'system', '', '手动断开连接')
  }

  function startReportTimer() {
    stopReportTimer()
    if (!state.connected || !state.autoReport) return
    state.reportTimer = window.setInterval(() => publishStatus('自动上报'), state.interval)
  }

  function stopReportTimer() {
    if (state.reportTimer) {
      window.clearInterval(state.reportTimer)
      state.reportTimer = null
    }
  }

  function updateAutoReportUI() {
    $('autoReport').checked = state.autoReport
    $('pauseReport').textContent = state.autoReport ? '暂停自动上报' : '恢复自动上报'
    if (state.connected) startReportTimer()
  }

  // ─────────── 场景 / 统计 / UI ───────────

  function applyPreset(name) {
    const preset = PRESETS[name]
    if (!preset) return
    METRICS.forEach((metric) => {
      if (preset[metric.key] == null) return
      metric.value = num(preset[metric.key], metric.digits)
      metric.base = metric.value
    })
    if (preset.gates) state.gates = preset.gates.slice()
    syncSensorUI()
    syncGateUI()
    renderPreview()
    log('sys', 'preset', preset.name, '已应用场景预设')
    if (state.connected) publishStatus(`场景预设：${preset.name}`)
  }

  function randomize() {
    METRICS.forEach((metric) => {
      const span = (metric.high ?? metric.max) - (metric.low ?? metric.min)
      const center = (metric.high ?? metric.max) + (metric.low ?? metric.min)
      const value = center / 2 + (Math.random() - 0.5) * span * 1.2
      metric.value = num(clamp(value, metric.min, metric.max), metric.digits)
      metric.base = metric.value
    })
    syncSensorUI()
    renderPreview()
    if (state.connected && state.autoReport) publishStatus('随机扰动')
  }

  function resetSensors() {
    applyPreset('normal')
  }

  function updateStats() {
    $('statTx').textContent = String(state.tx)
    $('statRx').textContent = String(state.rx)
    if (state.connected && state.connectedAt) {
      const seconds = Math.floor((Date.now() - state.connectedAt) / 1000)
      $('statUptime').textContent = `${pad(Math.floor(seconds / 3600))}:${pad(Math.floor(seconds % 3600 / 60))}:${pad(seconds % 60)}`
    } else {
      $('statUptime').textContent = '00:00:00'
    }
    if (state.lastStatusAt) {
      const seconds = Math.max(0, Math.floor((Date.now() - state.lastStatusAt) / 1000))
      $('statLast').textContent = seconds < 2 ? '刚刚' : `${seconds} 秒前`
    } else {
      $('statLast').textContent = '—'
    }
  }

  // ─────────── 日志 ───────────

  function log(direction, topic, payload, note = '') {
    if (state.logPaused) return
    const root = $('log')
    const empty = root.querySelector('.log__empty')
    if (empty) empty.remove()

    const item = document.createElement('div')
    item.className = 'log__item'

    const time = document.createElement('span')
    time.className = 'log__time'
    time.textContent = nowTime()

    const dir = document.createElement('span')
    const dirClass = direction === 'tx' ? 'tx' : direction === 'rx' ? 'rx' : direction === 'err' ? 'err' : 'sys'
    dir.className = `log__dir log__dir--${dirClass}`
    dir.textContent = dirClass.toUpperCase()

    const body = document.createElement('div')
    body.className = 'log__body'
    const topicEl = document.createElement('span')
    topicEl.className = 'log__topic'
    topicEl.textContent = topic || 'system'
    const payloadEl = document.createElement('span')
    payloadEl.className = 'log__payload'
    const raw = typeof payload === 'string' ? payload : JSON.stringify(payload)
    payloadEl.textContent = raw || '(空)'
    payloadEl.title = raw
    body.append(topicEl, payloadEl)
    if (note) {
      const noteEl = document.createElement('span')
      noteEl.className = 'log__note'
      noteEl.textContent = note
      body.appendChild(noteEl)
    }
    item.append(time, dir, body)
    root.appendChild(item)

    while (root.children.length > MAX_LOG) root.firstElementChild.remove()
    const nearBottom = root.scrollHeight - root.scrollTop - root.clientHeight < 50
    if (nearBottom) root.scrollTop = root.scrollHeight
    $('logMeta').textContent = `TX ${state.tx} · RX ${state.rx}`
  }

  function clearLog() {
    $('log').innerHTML = '<div class="log__empty">暂无消息</div>'
    $('logMeta').textContent = '已清空'
  }

  function togglePauseLog() {
    state.logPaused = !state.logPaused
    $('pauseLog').textContent = state.logPaused ? '继续' : '暂停'
    $('pauseLog').classList.toggle('btn--danger', state.logPaused)
  }

  async function copyStatus() {
    const text = $('statusPreview').textContent
    try {
      await navigator.clipboard.writeText(text)
      log('sys', 'clipboard', '', '最近上报报文已复制')
    } catch {
      const helper = document.createElement('textarea')
      helper.value = text
      helper.style.position = 'fixed'
      helper.style.opacity = '0'
      document.body.appendChild(helper)
      helper.select()
      document.execCommand('copy')
      helper.remove()
      log('sys', 'clipboard', '', '最近上报报文已复制（兼容模式）')
    }
  }

  // ─────────── 事件绑定 ───────────

  function bindEvents() {
    $('connectBtn').addEventListener('click', connect)
    $('disconnectBtn').addEventListener('click', disconnect)
    $('publishNow').addEventListener('click', () => publishStatus('手动上报'))
    $('heartbeat').addEventListener('click', publishHeartbeat)
    $('allOpen').addEventListener('click', () => setAllGates(1, '手动操作'))
    $('allClose').addEventListener('click', () => setAllGates(0, '手动操作'))
    $('loopback').addEventListener('click', loopback)
    $('injectControl').addEventListener('click', injectControl)
    $('randomize').addEventListener('click', randomize)
    $('resetSensors').addEventListener('click', resetSensors)
    $('copyStatus').addEventListener('click', copyStatus)
    $('clearLog').addEventListener('click', clearLog)
    $('pauseLog').addEventListener('click', togglePauseLog)
    $('pauseReport').addEventListener('click', () => {
      state.autoReport = !state.autoReport
      updateAutoReportUI()
      log('sys', 'system', '', state.autoReport ? '自动上报已恢复' : '自动上报已暂停')
    })
    $('autoReport').addEventListener('change', (event) => {
      state.autoReport = event.target.checked
      updateAutoReportUI()
      log('sys', 'system', '', state.autoReport ? '自动上报已开启' : '自动上报已关闭')
    })
    $('drift').addEventListener('change', (event) => {
      state.drift = event.target.checked
      log('sys', 'system', '', state.drift ? '传感器自动漂移已开启' : '传感器自动漂移已关闭')
    })
    $('formatControl').addEventListener('click', () => {
      try {
        $('rawControl').value = JSON.stringify(JSON.parse($('rawControl').value), null, 2)
      } catch (error) {
        log('err', 'local', $('rawControl').value, `格式化失败：${error.message}`)
      }
    })
    $('interval').addEventListener('change', () => {
      state.interval = clamp(Number($('interval').value) || 2000, 500, 60000)
      $('interval').value = String(state.interval)
      saveConfig()
      if (state.connected) startReportTimer()
      log('sys', 'system', '', `上报间隔调整为 ${state.interval} ms`)
    })
    ;['broker', 'clientId', 'statusTopic', 'controlTopic', 'username'].forEach((id) => {
      $(id).addEventListener('change', () => { saveConfig(); updateBrokerNotice() })
    })
    $('controlTopic').addEventListener('change', () => {
      if (!state.connected || !state.client) return
      const topic = readConfig().controlTopic
      state.client.subscribe(topic, { qos: 2 }, (error) => {
        if (error) log('err', topic, '', `新控制主题订阅失败：${error.message}`)
        else log('sys', topic, '', '控制主题已切换并重新订阅')
      })
    })
    $('broker').addEventListener('input', updateBrokerNotice)
    $('presetLocal').addEventListener('click', () => {
      $('broker').value = 'ws://127.0.0.1:8083/mqtt'
      updateBrokerNotice()
      saveConfig()
    })
    $('presetCloud').addEventListener('click', () => {
      $('broker').value = DEFAULT_BROKER
      updateBrokerNotice()
      saveConfig()
    })
    $('noticeUseLocal').addEventListener('click', () => {
      $('broker').value = 'ws://127.0.0.1:8083/mqtt'
      updateBrokerNotice()
      saveConfig()
    })
    document.querySelectorAll('[data-preset]').forEach((button) => {
      button.addEventListener('click', () => applyPreset(button.dataset.preset))
    })
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
        event.preventDefault()
        publishStatus('快捷键上报')
      }
    })
    $('log').innerHTML = '<div class="log__empty">暂无消息</div>'
  }

  document.addEventListener('DOMContentLoaded', init)
})()
