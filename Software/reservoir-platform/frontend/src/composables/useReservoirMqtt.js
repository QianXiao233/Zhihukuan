import { onBeforeUnmount, onMounted, ref } from 'vue'
import { MqttService, mqttOptions, mqttUrl } from '../utils/mqttService.js'

const STATUS_TOPIC = 'rtu/status'
const CONTROL_TOPIC = 'rtu/control'

function numberOrNull(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function normalizePayload(payload) {
  const validRelay = Array.isArray(payload?.relay)
    && payload.relay.length >= 6
    && payload.relay.slice(0, 6).every((value) => [0, 1, '0', '1'].includes(value))
  const relay = validRelay ? payload.relay.slice(0, 6).map((value) => Number(value) === 1 ? 1 : 0) : []
  while (relay.length < 6) relay.push(0)
  return {
    ...payload,
    relay,
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
  const gates = ref([0, 0, 0, 0, 0, 0])
  const service = new MqttService(mqttUrl(), mqttOptions())

  function handleMessage(topic, payload) {
    if (topic !== STATUS_TOPIC || !payload || typeof payload !== 'object') return
    const data = normalizePayload(payload)
    realtime.value = data
    gates.value = data.relay
  }

  function setGate(id, state) {
    const gateId = Number(id)
    const nextState = Number(state) === 1 ? 1 : 0
    if (gateId < 1 || gateId > 6) return false
    // RTU 控制协议：闸门编号使用 relay 字段，命令固定为 relay.set。
    // 例如开启 1 号闸门：{"cmd":"relay.set","relay":1,"state":1}
    const published = service.publish(CONTROL_TOPIC, { cmd: 'relay.set', relay: gateId, state: nextState }, { qos: 2 })
    // 只有后续 rtu/status 回报才更新显示状态，不把“指令已发布”冒充为闸门已动作。
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

  return { mqttConnected, realtime, gates, toggleGate, setGate }
}

export { STATUS_TOPIC, CONTROL_TOPIC }
