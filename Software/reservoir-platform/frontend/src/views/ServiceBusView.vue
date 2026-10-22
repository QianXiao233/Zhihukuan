<template>
  <ViewShell title="服务接入" :tag="`消息中转 · ${counts.total ?? 0} 条消息`" :icon="ApiOutlined">
    <div class="bus-page">
      <section class="engine-bar" :class="error ? 'is-offline' : 'is-online'">
        <span class="engine-dot"></span>
        <div class="engine-copy">
          <strong>{{ error ? '消息总线状态读取失败' : '消息总线运行中' }}</strong>
          <small v-if="error">{{ error }}</small>
          <small v-else>
            服务 A 发布 → 后端中转 → 服务 B 长轮询消费 · 至少一次投递 · 消息存 MongoDB
          </small>
        </div>
        <div class="engine-actions">
          <button class="plain-btn" type="button" :disabled="loading" @click="loadAll">
            <SyncOutlined /> {{ loading ? '刷新中…' : '刷新' }}
          </button>
        </div>
      </section>

      <div v-if="!canManage" class="alert-error" role="alert">只有管理员可以管理服务接入。</div>

      <template v-else>
        <section class="stat-grid">
          <article v-for="item in statCards" :key="item.key" class="stat-card" :class="{ 'is-warn': item.warn && counts[item.key] > 0 }">
            <small>{{ item.label }}</small>
            <strong>{{ counts[item.key] ?? 0 }}</strong>
            <span>{{ item.hint }}</span>
          </article>
        </section>

        <p v-if="message" class="tip" :class="{ bad: messageBad }">{{ message }}</p>

        <div class="bus-grid">
          <section class="view-card">
            <div class="card-head">
              <div>
                <h2 class="view-card__title"><PlusCircleOutlined /> 新建服务身份</h2>
                <p class="hint">密钥只在创建时显示一次；发布/订阅权限支持 <code>*</code>（一层）和 <code>#</code>（任意层）</p>
              </div>
            </div>
            <div class="preset-row">
              <button class="plain-btn" type="button" @click="applyPreset('sender')">填入告警发送方</button>
              <button class="plain-btn" type="button" @click="applyPreset('receiver')">填入处置接收方</button>
            </div>
            <form class="bus-form" @submit.prevent="createClient">
              <label>客户端 ID
                <input v-model.trim="form.clientId" required maxlength="64" placeholder="svc-a" autocomplete="off" />
                <small>2~64 位字母、数字、下划线或短横线，创建后不可修改</small>
              </label>
              <label>显示名称
                <input v-model.trim="form.clientName" maxlength="100" placeholder="告警服务" autocomplete="off" />
              </label>
              <label>可发布主题
                <input v-model.trim="form.allowPublish" maxlength="1000" placeholder="alarm.#" autocomplete="off" />
                <small>多个频道用英文逗号分隔，如 <code>alarm.#,device.#</code>；填 <code>none</code> 表示不允许发布</small>
              </label>
              <label>可订阅主题
                <input v-model.trim="form.allowSubscribe" maxlength="1000" placeholder="none" autocomplete="off" />
                <small>多个频道用英文逗号分隔，如 <code>alarm.#,device.#</code>；填 <code>none</code> 表示不允许订阅</small>
              </label>
              <div class="form-actions">
                <button class="primary-btn" type="submit" :disabled="creating">{{ creating ? '创建中…' : '创建并生成密钥' }}</button>
              </div>
            </form>
          </section>

          <section class="view-card">
            <h2 class="view-card__title"><ApiOutlined /> 接入方式</h2>
            <p class="hint">服务端用 <code>Authorization: Bearer &lt;clientId&gt;.&lt;secret&gt;</code> 调用下面四个接口。</p>
            <div class="api-list">
              <div class="api-row"><b class="method post">POST</b><code>/api/bus/publish</code><span>发布消息</span></div>
              <div class="api-row"><b class="method get">GET</b><code>/api/bus/pull</code><span>长轮询领取，最多挂 25 秒</span></div>
              <div class="api-row"><b class="method post">POST</b><code>/api/bus/ack</code><span>确认消费</span></div>
              <div class="api-row"><b class="method post">POST</b><code>/api/bus/nack</code><span>处理失败，退避重投</span></div>
            </div>
            <p class="hint">投递语义为至少一次：没 ack 会在租约（120 秒）到期后重投，消费方按 <code>msgId</code> 幂等；超过 5 次进死信。</p>
          </section>
        </div>

        <section class="view-card">
          <div class="card-head">
            <div>
              <h2 class="view-card__title"><CodeOutlined /> 服务调用示例</h2>
              <p class="hint">完整流程：发布 → 长轮询领取 → 确认消费。把 <code>&lt;clientId&gt;.&lt;secret&gt;</code> 换成创建客户端时保存的凭据。</p>
            </div>
            <div class="example-tabs">
              <button v-for="tab in exampleTabs" :key="tab.key" type="button" :class="{ 'is-active': exampleLang === tab.key }" @click="exampleLang = tab.key">{{ tab.label }}</button>
            </div>
          </div>
          <pre class="code-block">{{ examples[exampleLang] }}</pre>
          <div class="example-foot">
            <button class="plain-btn" type="button" @click="copyExample(examples[exampleLang], 'main')">{{ copiedKey === 'main' ? '已复制' : '复制示例' }}</button>
            <span class="hint">URL 里的 <code>%23</code> 就是 <code>#</code>；多个频道用英文逗号分隔。</span>
          </div>
          <details class="snippet">
            <summary>推送前端弹窗（ui.notice）</summary>
            <pre>{{ noticeExample }}</pre>
          </details>
        </section>

        <section class="view-card">
          <div class="card-head">
            <div>
              <h2 class="view-card__title"><TeamOutlined /> 已接入服务</h2>
              <p class="hint">停用后该服务的密钥立即失效；轮换密钥会让旧密钥立刻不可用。</p>
            </div>
            <span class="count-note">{{ clients.length }} 个客户端</span>
          </div>
          <div class="table-wrap">
            <table class="bus-table">
              <thead>
                <tr>
                  <th>客户端</th>
                  <th>可发布</th>
                  <th>可订阅</th>
                  <th>状态</th>
                  <th>创建时间</th>
                  <th class="actions-col">操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="client in clients" :key="client.clientId">
                  <td>
                    <strong class="client-name">{{ client.clientName }}</strong>
                    <code class="client-id">{{ client.clientId }}</code>
                  </td>
                  <td><span v-for="pattern in patterns(client.allowPublish)" :key="pattern" class="pattern" :class="{ muted: pattern === 'none' }">{{ pattern }}</span></td>
                  <td><span v-for="pattern in patterns(client.allowSubscribe)" :key="pattern" class="pattern" :class="{ muted: pattern === 'none' }">{{ pattern }}</span></td>
                  <td><span class="state" :class="client.enabled ? 'on' : 'off'">{{ client.enabled ? '已启用' : '已停用' }}</span></td>
                  <td class="time">{{ formatTime(client.createdAt) }}</td>
                  <td class="actions-col">
                    <button class="link-btn" type="button" @click="openExample(client)">示例</button>
                    <button class="link-btn" type="button" @click="toggleClient(client)">{{ client.enabled ? '停用' : '启用' }}</button>
                    <button class="link-btn" type="button" @click="rotateClient(client)">轮换密钥</button>
                    <button class="link-btn danger" type="button" @click="removeClient(client)">删除</button>
                  </td>
                </tr>
                <tr v-if="!clients.length">
                  <td colspan="6" class="empty">还没有接入服务，先在左上角创建一个客户端。</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </template>
    </div>

    <div v-if="secretInfo" class="modal-mask" @click.self="secretInfo = null" @keydown.esc="secretInfo = null">
      <div class="modal-card" role="dialog" aria-modal="true" aria-label="服务密钥">
        <h3>密钥只显示这一次</h3>
        <p>把完整凭据保存到对应服务的配置里，关闭后无法再次查看；丢了只能轮换。</p>
        <code class="secret">{{ secretInfo.clientId }}.{{ secretInfo.secret }}</code>
        <div class="modal-actions">
          <button class="primary-btn" type="button" @click="copySecret">{{ copied ? '已复制' : '复制凭据' }}</button>
          <button class="plain-btn" type="button" @click="secretInfo = null">我已保存</button>
        </div>
      </div>
    </div>
    <div v-if="exampleClient" class="modal-mask" @click.self="exampleClient = null" @keydown.esc="exampleClient = null">
      <div class="modal-card example-modal" role="dialog" aria-modal="true" aria-label="服务调用示例">
        <div class="card-head">
          <div>
            <h3>调用示例 · {{ exampleClient.clientId }}</h3>
            <p class="hint">把 <code>&lt;secret&gt;</code> 换成这个客户端的密钥；发布主题要落在它的可发布范围内。</p>
          </div>
          <button class="close-btn" type="button" aria-label="关闭" @click="exampleClient = null">×</button>
        </div>
        <div class="example-tabs">
          <button v-for="tab in exampleTabs" :key="tab.key" type="button" :class="{ 'is-active': modalLang === tab.key }" @click="modalLang = tab.key">{{ tab.label }}</button>
        </div>
        <pre class="code-block example-code">{{ modalExamples[modalLang] }}</pre>
        <div class="example-foot">
          <button class="plain-btn" type="button" @click="copyExample(modalExamples[modalLang], 'modal')">{{ copiedKey === 'modal' ? '已复制' : '复制示例' }}</button>
        </div>
      </div>
    </div>
  </ViewShell>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ApiOutlined, CodeOutlined, PlusCircleOutlined, SyncOutlined, TeamOutlined } from '@ant-design/icons-vue'
import ViewShell from './ViewShell.vue'
import {
  createBusClient,
  deleteBusClient,
  listBusStatus,
  rotateBusClient,
  setBusClientEnabled,
} from '../api/manageApi.js'

const level = Number(localStorage.getItem('level') ?? 1)
const canManage = level === 0 || level >= 3
const origin = `${window.location.protocol}//${window.location.host}`

const loading = ref(false)
const creating = ref(false)
const error = ref('')
const message = ref('')
const messageBad = ref(false)
const copied = ref(false)
const secretInfo = ref(null)
const counts = ref({})
const clients = ref([])

const form = reactive({ clientId: '', clientName: '', allowPublish: 'alarm.#', allowSubscribe: 'none' })

const statCards = [
  { key: 'pending', label: '待投递', hint: '等待消费方领取' },
  { key: 'processing', label: '处理中', hint: '已领取未 ack' },
  { key: 'delivered', label: '已投递', hint: '保留至 TTL 到期' },
  { key: 'dead', label: '死信', hint: '重试次数用尽', warn: true },
]

// ─────────── 服务调用示例 ───────────

const exampleTabs = [
  { key: 'curl', label: 'cURL' },
  { key: 'java', label: 'Java' },
  { key: 'python', label: 'Python' },
  { key: 'node', label: 'Node.js' },
]
const exampleLang = ref('curl')
const modalLang = ref('curl')
const exampleClient = ref(null)
const copiedKey = ref('')

function buildExamples(clientId) {
  const auth = `${clientId}.<secret>`
  const curl = [
    `export BASE=${origin}`,
    `export AUTH='${auth}'`,
    '',
    '# 1) 发布消息',
    'curl -s -X POST "$BASE/api/bus/publish" \\',
    '  -H "Authorization: Bearer $AUTH" \\',
    '  -H \'Content-Type: application/json\' \\',
    '  -d \'{"topic":"alarm.dam1.level","target":"svc-b","payload":{"level":1.83,"threshold":1.2}}\'',
    '',
    '# 2) 长轮询领取（没有消息时最多挂 25 秒）',
    'curl -s "$BASE/api/bus/pull?topic=alarm.%23&limit=20&wait=25" \\',
    '  -H "Authorization: Bearer $AUTH"',
    '',
    '#    多频道：topic 可传多个模式，逗号分隔',
    'curl -s "$BASE/api/bus/pull?topic=alarm.%23,device.%23&limit=20&wait=25" \\',
    '  -H "Authorization: Bearer $AUTH"',
    '',
    '# 3) 确认消费（不 ack 会在租约到期后重投）',
    'curl -s -X POST "$BASE/api/bus/ack" \\',
    '  -H "Authorization: Bearer $AUTH" \\',
    '  -H \'Content-Type: application/json\' \\',
    '  -d \'{"msgIds":["<msgId>"]}\'',
  ].join('\n')

  const java = [
    'import java.net.URI;',
    'import java.net.URLEncoder;',
    'import java.net.http.*;',
    'import java.nio.charset.StandardCharsets;',
    '',
    `String base = "${origin}";`,
    `String auth = "Bearer ${auth}";`,
    'HttpClient http = HttpClient.newHttpClient();',
    '',
    '// 1) 发布',
    'String body = """',
    '    {"topic":"alarm.dam1.level","target":"svc-b","payload":{"level":1.83}}',
    '    """;',
    'http.send(HttpRequest.newBuilder(URI.create(base + "/api/bus/publish"))',
    '        .header("Authorization", auth)',
    '        .header("Content-Type", "application/json")',
    '        .POST(HttpRequest.BodyPublishers.ofString(body)).build(),',
    '    HttpResponse.BodyHandlers.ofString());',
    '',
    '// 2) 长轮询领取',
    'String topic = URLEncoder.encode("alarm.#", StandardCharsets.UTF_8);',
    'String json = http.send(HttpRequest.newBuilder(URI.create(',
    '        base + "/api/bus/pull?topic=" + topic + "&limit=20&wait=25"))',
    '        .header("Authorization", auth).GET().build(),',
    '    HttpResponse.BodyHandlers.ofString()).body();',
    'System.out.println(json);',
    '',
    '// 3) 解析 msgId 后确认（JSON 解析用项目现有库）',
    'String ack = """',
    '    {"msgIds":["<msgId>"]}',
    '    """;',
    'http.send(HttpRequest.newBuilder(URI.create(base + "/api/bus/ack"))',
    '        .header("Authorization", auth)',
    '        .header("Content-Type", "application/json")',
    '        .POST(HttpRequest.BodyPublishers.ofString(ack)).build(),',
    '    HttpResponse.BodyHandlers.ofString());',
  ].join('\n')

  const python = [
    'import requests',
    '',
    `BASE = "${origin}"`,
    `HEADERS = {"Authorization": "Bearer ${auth}"}`,
    '',
    '# 1) 发布',
    'requests.post(BASE + "/api/bus/publish", headers=HEADERS, timeout=10, json={',
    '    "topic": "alarm.dam1.level",',
    '    "target": "svc-b",',
    '    "payload": {"level": 1.83, "threshold": 1.2},',
    '})',
    '',
    '# 2) 长轮询领取（最多挂 25 秒）',
    'resp = requests.get(BASE + "/api/bus/pull", headers=HEADERS, timeout=40,',
    '                    params={"topic": "alarm.#", "limit": 20, "wait": 25})',
    'for msg in resp.json()["messages"]:',
    '    print(msg["msgId"], msg["payload"])',
    '',
    '    # 3) 确认消费',
    '    requests.post(BASE + "/api/bus/ack", headers=HEADERS, timeout=10,',
    '                  json={"msgIds": [msg["msgId"]]})',
  ].join('\n')

  const node = [
    `const BASE = '${origin}'`,
    'const headers = {',
    `  Authorization: 'Bearer ${auth}',`,
    "  'Content-Type': 'application/json',",
    '}',
    '',
    '// 1) 发布',
    "await fetch(BASE + '/api/bus/publish', {",
    "  method: 'POST',",
    '  headers,',
    '  body: JSON.stringify({',
    "    topic: 'alarm.dam1.level',",
    "    target: 'svc-b',",
    '    payload: { level: 1.83, threshold: 1.2 },',
    '  }),',
    '})',
    '',
    '// 2) 长轮询领取（没有消息时最多挂 25 秒）',
    'const res = await fetch(',
    "  BASE + '/api/bus/pull?topic=' + encodeURIComponent('alarm.#') + '&limit=20&wait=25',",
    '  { headers },',
    ')',
    'const { messages } = await res.json()',
    'for (const msg of messages) {',
    '  console.log(msg.msgId, msg.payload)',
    '',
    '  // 3) 确认消费',
    "  await fetch(BASE + '/api/bus/ack', {",
    "    method: 'POST',",
    '    headers,',
    '    body: JSON.stringify({ msgIds: [msg.msgId] }),',
    '  })',
    '}',
  ].join('\n')

  return { curl, java, python, node }
}

const examples = computed(() => buildExamples('<clientId>'))
const modalExamples = computed(() => buildExamples(exampleClient.value?.clientId || '<clientId>'))

const noticeExample = [
  `curl -s -X POST "${origin}/api/bus/publish" \\`,
  '  -H "Authorization: Bearer <clientId>.<secret>" \\',
  '  -H \'Content-Type: application/json\' \\',
  '  -d \'{"topic":"ui.notice","payload":{"title":"水位异常","content":"坝前水位 1.83m，超过阈值 1.2m","level":2,"popup":true,"sound":true}}\'',
].join('\n')

function openExample(client) {
  exampleClient.value = client
  modalLang.value = 'curl'
}

async function copyExample(text, key) {
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    window.setTimeout(() => {
      if (copiedKey.value === key) copiedKey.value = ''
    }, 1800)
  } catch {
    window.prompt('复制下面的示例', text)
  }
}

let timer

async function loadAll() {
  if (!canManage) return
  loading.value = true
  error.value = ''
  try {
    const data = (await listBusStatus()).data || {}
    counts.value = data.counts || {}
    clients.value = data.clients || []
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function applyPreset(kind) {
  if (kind === 'sender') {
    form.allowPublish = 'alarm.#'
    form.allowSubscribe = 'none'
    if (!form.clientName) form.clientName = '告警服务'
  } else {
    form.allowPublish = 'none'
    form.allowSubscribe = 'alarm.#'
    if (!form.clientName) form.clientName = '处置服务'
  }
}

async function createClient() {
  message.value = ''
  messageBad.value = false
  if (!/^[A-Za-z0-9_-]{2,64}$/.test(form.clientId)) {
    message.value = '客户端 ID 只能是 2~64 位字母、数字、下划线或短横线'
    messageBad.value = true
    return
  }
  creating.value = true
  try {
    const data = (await createBusClient({
      clientId: form.clientId,
      clientName: form.clientName,
      allowPublish: form.allowPublish,
      allowSubscribe: form.allowSubscribe,
    })).data
    secretInfo.value = { clientId: data.client.clientId, secret: data.secret }
    form.clientId = ''
    form.clientName = ''
    await loadAll()
  } catch (e) {
    message.value = e.message
    messageBad.value = true
  } finally {
    creating.value = false
  }
}

async function toggleClient(client) {
  message.value = ''
  try {
    await setBusClientEnabled(client.clientId, !client.enabled)
    await loadAll()
  } catch (e) {
    message.value = e.message
    messageBad.value = true
  }
}

async function rotateClient(client) {
  if (!window.confirm(`轮换「${client.clientName}」的密钥？旧密钥会立即失效，使用它的服务需要同步更新。`)) return
  message.value = ''
  try {
    const data = (await rotateBusClient(client.clientId)).data
    secretInfo.value = { clientId: data.clientId, secret: data.secret }
  } catch (e) {
    message.value = e.message
    messageBad.value = true
  }
}

async function removeClient(client) {
  if (!window.confirm(`删除「${client.clientName}」（${client.clientId}）？该服务将立即无法发布或领取消息。`)) return
  message.value = ''
  try {
    await deleteBusClient(client.clientId)
    message.value = `已删除 ${client.clientId}`
    messageBad.value = false
    await loadAll()
  } catch (e) {
    message.value = e.message
    messageBad.value = true
  }
}

function patterns(value) {
  const list = String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
  return list.length ? list : ['none']
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).replace('T', ' ').slice(0, 16)
  const pad = (part) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

async function copySecret() {
  const text = `${secretInfo.value.clientId}.${secretInfo.value.secret}`
  try {
    await navigator.clipboard.writeText(text)
    copied.value = true
    window.setTimeout(() => { copied.value = false }, 1800)
  } catch {
    window.prompt('复制下面的凭据', text)
  }
}

onMounted(() => {
  void loadAll()
  timer = window.setInterval(loadAll, 15000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.bus-page{display:grid;gap:14px}
.engine-bar{display:flex;align-items:center;gap:12px;padding:14px 18px;border:1px solid #dcebf2;border-radius:14px;background:rgba(255,255,255,.94);box-shadow:0 8px 20px rgba(31,80,117,.05)}
.engine-bar.is-online .engine-dot{background:#27bd94;box-shadow:0 0 0 4px rgba(39,189,148,.14)}
.engine-bar.is-offline .engine-dot{background:#e0736b;box-shadow:0 0 0 4px rgba(224,115,107,.14)}
.engine-dot{width:10px;height:10px;border-radius:50%;flex:0 0 10px}
.engine-copy{display:grid;gap:3px;flex:1;min-width:0}
.engine-copy strong{color:#1b3e5c;font-size:14px}
.engine-copy small{color:#8297a6;font-size:11px;overflow-wrap:anywhere}
.engine-actions{display:flex;gap:8px}
.stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px}
.stat-card{display:grid;gap:4px;padding:14px 16px;border:1px solid #e2ebf3;border-radius:13px;background:rgba(255,255,255,.94);box-shadow:0 6px 18px rgba(31,80,117,.05)}
.stat-card small{color:#8ca0ae;font-size:11px}
.stat-card strong{color:#1b3e5c;font-size:23px;font-weight:650;line-height:1.2}
.stat-card span{color:#9aacb8;font-size:10px}
.stat-card.is-warn{border-color:#f2cdc8;background:#fff7f5}
.stat-card.is-warn strong{color:#c65b52}
.bus-grid{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr);gap:14px}
.view-card{padding:18px;border:1px solid #e2ebf3;border-radius:15px;background:rgba(255,255,255,.93);box-shadow:0 8px 22px rgba(31,80,117,.06)}
.view-card__title{display:flex;align-items:center;gap:8px;margin:0 0 6px;color:#1b3e5c;font-size:14px;font-weight:650}
.hint{margin:0 0 12px;color:#8a9daa;font-size:11px;line-height:1.7}
.hint code,.bus-form code{color:#2f6f9e;background:#eff6fb;border-radius:4px;padding:1px 4px;font-size:10px}
.card-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:10px}
.preset-row{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:12px}
.bus-form{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.bus-form label{display:grid;gap:5px;color:#617b90;font-size:12px}
.bus-form label small{color:#9aacb8;font-size:10px;line-height:1.5}
.bus-form input{height:36px;border:1px solid #dce8f0;border-radius:8px;padding:0 10px;background:#fbfdfe;color:#315571;font-size:12px}
.bus-form input:focus{outline:none;border-color:#7db6e0;box-shadow:0 0 0 3px rgba(22,121,209,.08)}
.bus-form label:nth-child(3),.bus-form label:nth-child(4){grid-column:1 / -1}
.form-actions{grid-column:1 / -1;display:flex;gap:8px;padding-top:2px}
.primary-btn,.plain-btn{height:34px;padding:0 14px;border-radius:8px;font-size:12px;cursor:pointer;transition:.15s}
.primary-btn{border:0;background:#1679d1;color:#fff}
.primary-btn:hover{background:#1269ba}
.primary-btn:disabled,.plain-btn:disabled{opacity:.55;cursor:not-allowed}
.plain-btn{border:1px solid #d7e5ef;background:#fff;color:#4a6b82;display:inline-flex;align-items:center;gap:6px}
.plain-btn:hover{border-color:#9cc4e0;color:#1679d1}
.link-btn{border:0;background:none;padding:0;color:#1679d1;font-size:11px;cursor:pointer}
.link-btn:hover{text-decoration:underline}
.link-btn.danger{color:#cf6b62}
.tip{margin:0;padding:9px 12px;border-radius:8px;background:#effaf4;color:#13875f;font-size:11px}
.tip.bad{background:#fff1ef;color:#bd5350}
.alert-error{padding:12px;border-radius:9px;background:#fff1ef;color:#bd5350;font-size:12px}
.api-list{display:grid;gap:7px;margin-bottom:12px}
.api-row{display:flex;align-items:center;gap:8px;font-size:11px;color:#617b90}
.api-row code{flex:1;color:#315571;font-size:11px}
.method{flex:0 0 42px;text-align:center;border-radius:5px;padding:2px 0;font-size:9px;letter-spacing:.04em}
.method.post{background:#e8f3fc;color:#1679d1}
.method.get{background:#e8f8f0;color:#13875f}
.snippet{margin:4px 0 10px;border:1px solid #e4edf4;border-radius:9px;background:#f7fbfe;overflow:hidden}
.snippet summary{padding:9px 12px;color:#4a6b82;font-size:11px;cursor:pointer}
.snippet pre{margin:0;padding:12px;overflow:auto;border-top:1px solid #e4edf4;color:#2f5570;font-size:10px;line-height:1.7}
.count-note{color:#8ca0ae;font-size:11px}
.table-wrap{overflow:auto}
.bus-table{width:100%;border-collapse:collapse;font-size:11px}
.bus-table th{padding:9px 10px;text-align:left;color:#8ca0ae;font-weight:500;border-bottom:1px solid #e9f0f5;white-space:nowrap}
.bus-table td{padding:11px 10px;border-bottom:1px solid #eef4f8;color:#4a6b82;vertical-align:middle}
.bus-table tr:last-child td{border-bottom:0}
.client-name{display:block;color:#294b66;font-size:12px}
.client-id{display:inline-block;margin-top:3px;padding:1px 5px;border-radius:4px;background:#f1f6fa;color:#6b8497;font-size:10px}
.pattern{display:inline-block;margin:1px 3px 1px 0;padding:2px 6px;border-radius:4px;background:#eef7ff;color:#2f6f9e;font-size:10px}
.pattern.muted{background:#f3f5f7;color:#9aa9b4}
.state{display:inline-block;padding:2px 8px;border-radius:10px;font-size:10px}
.state.on{background:#e8f8f0;color:#13875f}
.state.off{background:#f3f5f7;color:#8a9aa5}
.time{color:#8297a6;white-space:nowrap}
.actions-col{text-align:right;white-space:nowrap;display:table-cell}
.actions-col .link-btn{margin-left:10px}
.empty{padding:26px 0;text-align:center;color:#9aacb8}
.modal-mask{position:fixed;inset:0;z-index:60;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(16,42,62,.48);backdrop-filter:blur(3px)}
.modal-card{width:min(560px,100%);padding:22px;border-radius:16px;background:#fff;box-shadow:0 24px 60px rgba(9,35,55,.28)}
.modal-card h3{margin:0 0 8px;color:#1b3e5c;font-size:16px}
.modal-card p{margin:0 0 14px;color:#7b8f9e;font-size:12px;line-height:1.7}
.secret{display:block;padding:13px;border:1px solid #dce8f0;border-radius:9px;background:#f7fbfe;color:#1f4d6d;font-size:12px;word-break:break-all;user-select:all}
.modal-actions{display:flex;gap:9px;margin-top:16px}
@media (max-width:1100px){.bus-grid{grid-template-columns:1fr}}
@media (max-width:620px){.bus-form{grid-template-columns:1fr}.bus-form label:nth-child(3),.bus-form label:nth-child(4){grid-column:auto}}
.examples-card .card-head{align-items:center}
.example-tabs{display:flex;flex-wrap:wrap;gap:4px}
.example-tabs button{height:28px;padding:0 10px;border:1px solid #dce8f0;border-radius:7px;background:#fff;color:#6b8497;font-size:11px;cursor:pointer;transition:.15s}
.example-tabs button:hover{border-color:#9cc4e0;color:#1679d1}
.example-tabs button.is-active{border-color:#1679d1;background:#eef7ff;color:#1679d1}
.code-block{margin:0 0 12px;padding:14px 16px;border-radius:10px;background:#0f2a3d;color:#d6e6f2;font-size:11px;line-height:1.8;overflow:auto;max-height:420px;white-space:pre;tab-size:2}
.example-foot{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.example-foot .hint{margin:0}
.example-modal{width:min(860px,100%);max-height:90vh;overflow:auto}
.example-modal h3{margin:0 0 6px;color:#1b3e5c;font-size:16px}
.example-code{max-height:52vh}
.close-btn{flex:0 0 30px;width:30px;height:30px;border:0;border-radius:8px;background:#f1f6fa;color:#70879a;font-size:18px;line-height:1;cursor:pointer}
.close-btn:hover{background:#e6f1f9;color:#1679d1}
</style>
