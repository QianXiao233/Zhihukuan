import { onBeforeUnmount, onMounted, ref } from 'vue'
import { MqttService, mqttOptions, mqttUrl } from '../utils/mqttService.js'

const STATUS_TOPIC = 'rtu/status'
const CONTROL_TOPIC = 'rtu/control'

/**
 * 参与放水调度的闸门数量。
 *
 * 现场接入 6 路继电器，但职责不同：
 * - **1~4 号：放水闸门**，开得越多水位降得越快（AI 决策只管这 4 路）；
 * - **5~6 号：循环回抽泵**，仅用于采集训练数据时把水抽回水箱做自循环，
 *   生产运行不参与调度。5 号水量小、6 号水量大。
 *
 * 因此界面上的"闸门"只展示 1~4，避免运维误以为 5/6 也能当调度手段用。
 */
export const SCHEDULE_GATE_COUNT = 4
/** 继电器总路数（固件 RELAY_COUNT），回抽泵仍会读状态但不做调度展示 */
export const RELAY_TOTAL = 6

function numberOrNull(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizePayload(payload) {
  const validRelay = Array.isArray(payload?.relay)
    && payload.relay.length >= RELAY_TOTAL
    && payload.relay.slice(0, RELAY_TOTAL).every((value) => [0, 1, '0', '1'].includes(value))
  const all = validRelay
    ? payload.relay.slice(0, RELAY_TOTAL).map((value) => (Number(value) === 1 ? 1 : 0))
    : Array(RELAY_TOTAL).fill(0)
  return {
    ...payload,
    relay: all,
    // 只有放水闸门（1~4）参与调度展示与 AI 决策
    gates: all.slice(0, SCHEDULE_GATE_COUNT),
    pumps: all.slice(SCHEDULE_GATE_COUNT),
    relayReported: validRelay,
    level: numberOrNull(payload?.level ?? payload?.liquidLevel ?? payload?.waterLevel),
    temp: numberOrNull(payload?.temp ?? payload?.temperature),
    ph: numberOrNull(payload?.ph ?? payload?.pH),
    orp: numberOrNull(payload?.orp ?? payload?.ORP),
    receivedAt: Date.now(),
  }
}

/** 水库 RTU 的前端 MQTT 直连：传感器状态订阅 + 闸门控制发布。 */
export function useReservoirMqtt() {
  const mqttConnected = ref(false)
  const realtime = ref(null)
  const gates = ref(Array(SCHEDULE_GATE_COUNT).fill(0))
  const pumps = ref(Array(RELAY_TOTAL - SCHEDULE_GATE_COUNT).fill(0))
  const service = new MqttService(mqttUrl(), mqttOptions())

  function handleMessage(topic, payload) {
    if (topic !== STATUS_TOPIC || !payload || typeof payload !== 'object') return
    const data = normalizePayload(payload)
    realtime.value = data
    gates.value = data.gates
    pumps.value = data.pumps
  }

  function setGate(id, state) {
    const gateId = Number(id)
    const nextState = Number(state) === 1 ? 1 : 0
    if (gateId < 1 || gateId > RELAY_TOTAL) return false
    // RTU 控制协议：闸门编号使用 relay 字段，命令固定为 relay.set。
    // 例如开启 1 号闸门：{"cmd":"relay.set","relay":1,"state":1}
    const published = service.publish(CONTROL_TOPIC, { cmd: 'relay.set', relay: gateId, state: nextState }, { qos: 2 })
    // 只有后续 rtu/status 回报才更新显示状态，不把"指令已发布"冒充为闸门已动作。
    return published
  }

  function toggleGate(id) {
    const gateId = Number(id)
    return setGate(gateId, gates.value[gateId - 1] === 1 ? 0 : 1)
  }

  onMounted(() => {
    service.onStatus((status) => { mqttConnected.value = status === 'connected' })
    service.onMessage(handleMessage)
    service.connect()
    service.subscribe(STATUS_TOPIC, { qos: 0 }, (error) => {
      if (error) console.warn('[MQTT] rtu/status subscribe failed', error.message)
    })
  })

  onBeforeUnmount(() => service.disconnect())

  return { mqttConnected, realtime, gates, pumps, toggleGate, setGate }
}

export { STATUS_TOPIC, CONTROL_TOPIC }
