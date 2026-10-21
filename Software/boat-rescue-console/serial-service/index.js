import http from 'node:http';
import { WebSocketServer } from 'ws';
import { SerialPort } from 'serialport';
import { encodeGroundToBoat } from './protocol.js';

const host = process.env.CONTROL_HOST || '127.0.0.1';
const port = Number(process.env.CONTROL_PORT || 4174);
const clients = new Set();
let serial = null;
/**
 * 串口是否真正可用。
 *
 * 为什么不直接用 `serial.isOpen`：那是 serialport 库缓存的标志位，
 * 当句柄在底层失效（设备被拔出、被别的进程抢占）时它可能仍是 true，
 * 于是服务端"以为"连着、实际写入会抛 "Port is not open"。
 * 这里用独立标志，在 open/close/error 三处同步维护。
 */
let serialReady = false;
let command = { armed: false, mode: 'manual', throttle: 0, steer: 0, navigation: null };
let lastCommandAt = 0;
let rx = Buffer.alloc(0);
let telemetry = null;

/**
 * 视觉定位程序（Python）推送的坐标。
 *
 * 与网页手动填写的 navigation 分开存放，互不干扰；哪个"活着"由新鲜度决定：
 *   - visionNav 在 VISION_TIMEOUT_MS 内被更新过 -> 用视觉坐标，进入自主航行
 *   - 否则                                    -> 用网页的值
 *
 * 这样网页和视觉程序可以同时运行，不会互相覆盖。
 */
const VISION_TIMEOUT_MS = 400;
let visionNav = null;
let visionNavAt = 0;

function visionNavFresh() {
  return visionNav !== null && (Date.now() - visionNavAt) <= VISION_TIMEOUT_MS;
}

/**
 * 投放释放：一次性动作。
 *
 * 触发后在 RELEASE_HOLD_MS 内以 mission_state=2 / release_flag=1 下发，
 * 之后自动恢复为原来的模式（手动或自主）。
 *
 * 为什么用时间窗而不是"发一帧就完"：
 *   串口帧可能丢失，而投放是不可逆动作 —— 重复执行只是舵机多动一次（无害，
 *   船端也会在动作期间忽略重复触发），但漏执行则整个救援任务失败。
 *   所以宁可多发几帧保证送达，由船端的"动作期间忽略重复"来防重复投放。
 */
const RELEASE_HOLD_MS = 200;
let releaseUntil = 0;

function releaseActive() {
  return Date.now() < releaseUntil;
}

const server = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') return res.writeHead(204).end();

  if (req.url === '/api/ports') {
    try {
      const ports = await SerialPort.list();
      // 只保留"真实硬件"串口：蓝牙虚拟串口（BTHENUM）永远不是我们要控制的板子，
      // 混在列表里只会让人选错。VID 暴露出去供前端识别 Espressif 设备。
      const hardware = ports
        .filter(({ pnpId }) => !/^BTHENUM/i.test(String(pnpId || '')))
        .map(({ path, manufacturer, friendlyName, vendorId, productId, pnpId }) => ({
          path,
          manufacturer,
          friendlyName,
          vendorId: vendorId || null,
          productId: productId || null,
          pnpId: pnpId || null,
          // ESP32 系列原生 USB（USB-Serial-JTAG）的 Espressif VID
          isEspressif: String(vendorId || '').toUpperCase() === '303A',
        }));
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify(hardware));
    } catch (error) {
      res.writeHead(500, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ error: error.message }));
    }
  }

  if (req.url === '/api/status') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({
      connected: serialReady,
      port: serial?.path ?? null,
      telemetry,
      vision: visionNavFresh()
        ? { active: true, ageMs: Date.now() - visionNavAt, navigation: visionNav }
        : { active: false, ageMs: visionNav === null ? null : Date.now() - visionNavAt, navigation: visionNav },
      releasing: releaseActive(),
    }));
  }

  /**
   * 视觉定位程序推送坐标（由 the Python vision locator 调用）。
   * Body: { boatX, boatY, heading, targetX, targetY }
   *
   * 收到后 server 会在 VISION_TIMEOUT_MS 内优先使用这套坐标，
   * 并以 mission_state=1（自主航行）下发，直到停止推送。
   */
  if (req.url === '/api/navigation' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      let parsed;
      try {
        parsed = JSON.parse(body || '{}');
      } catch {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({ error: 'invalid JSON' }));
      }
      if (!validNavigation(parsed)) {
        res.writeHead(400, { 'Content-Type': 'application/json' });
        return res.end(JSON.stringify({
          error: 'coordinates out of range: X/Y must be 0-1.2 m, heading 0-360',
        }));
      }
      visionNav = {
        boatX: Number(parsed.boatX),
        boatY: Number(parsed.boatY),
        heading: Number(parsed.heading),
        targetX: Number(parsed.targetX),
        targetY: Number(parsed.targetY),
      };
      visionNavAt = Date.now();
      res.writeHead(200, { 'Content-Type': 'application/json' });
      return res.end(JSON.stringify({ ok: true, navigation: visionNav }));
    });
    return;
  }

  /** 视觉程序停止推送时调用，交还控制权给网页 */
  if (req.url === '/api/navigation' && req.method === 'DELETE') {
    visionNav = null;
    visionNavAt = 0;
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ ok: true }));
  }

  if (req.url === '/api/connect' && req.method === 'POST') {
    let body = '';
    req.on('data', (chunk) => { body += chunk; });
    req.on('end', () => {
      const selectedPort = JSON.parse(body).port;
      if (!selectedPort || typeof selectedPort !== 'string') {
        res.writeHead(400).end('Missing serial port');
        return;
      }
      const openNew = () => {
        serial = new SerialPort({ path: selectedPort, baudRate: 115200, autoOpen: false });

        serial.on('data', (data) => parseTelemetry(data));

        serial.on('error', (error) => {
          // 串口错误（如设备被拔出、句柄失效）意味着链路已不可用，
          // 必须把状态置回未连接，否则界面会一直显示"已连接"但发不出指令。
          serialReady = false;
          console.error(`[serial] 错误: ${error.message}`);
          broadcast({ type: 'error', message: `串口错误: ${error.message}` });
          broadcast({ type: 'connection', connected: false, port: selectedPort });
        });

        serial.on('close', () => {
          serialReady = false;
          command = { armed: false, mode: 'manual', throttle: 0, steer: 0, navigation: null };
          broadcast({ type: 'connection', connected: false, port: selectedPort });
        });

        serial.open((error) => {
          if (error) {
            serialReady = false;
            res.writeHead(500, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: error.message }));
            return;
          }
          serialReady = true;
          command = { armed: false, mode: 'manual', throttle: 0, steer: 0, navigation: null };
          lastCommandAt = Date.now();
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify({ connected: true, port: selectedPort }));
          broadcast({ type: 'connection', connected: true, port: selectedPort });
        });
      };

      /**
       * 必须等旧连接**真正关闭**再打开新连接。
       *
       * `serial.close()` 是异步的：调用后立刻 open() 会因 OS 尚未释放端口而
       * 报 "Access denied"；更糟的是旧连接已经被关掉，界面就变成"已连接"
       * 假象或直接断开。这就是之前"重复点连接 -> Port is not open"的根因。
       */
      const old = serial;
      serialReady = false;

      if (old) {
        let settled = false;
        const proceed = () => {
          if (settled) return;
          settled = true;
          openNew();
        };
        try {
          old.close(proceed);
        } catch {
          proceed();
        }
        // 兜底：close 回调在某些异常路径下可能不触发，避免请求一直挂着
        setTimeout(proceed, 500);
      } else {
        openNew();
      }
    });
    return;
  }

  if (req.url === '/api/disconnect' && req.method === 'POST') {
    command = { armed: false, mode: 'manual', throttle: 0, steer: 0, navigation: null };
    if (serial) { try { serial.close(() => {}); } catch { /* 已关闭 */ } }
    serialReady = false;
    res.writeHead(200, { 'Content-Type': 'application/json' });
    return res.end(JSON.stringify({ connected: false }));
  }

  res.writeHead(404).end('Not found');
});

const wss = new WebSocketServer({ server });
wss.on('connection', (socket) => {
  clients.add(socket);
  socket.send(JSON.stringify({ type: 'connection', connected: serialReady, port: serial?.path ?? null, telemetry }));
  socket.on('message', (raw) => {
    try {
      const next = JSON.parse(raw.toString());
      if (next.type === 'command') {
        // 注意：navigation 为 null 是**合法且有意义**的 —— 表示"纯二哈视觉搜救"模式。
        // 若此处把 null 换成全 0 坐标，船端会误判为有效坐标并走坐标导航。
        const nav = (next.navigation === null || next.navigation === undefined)
          ? null
          : (validNavigation(next.navigation) ? next.navigation : null);

        command = {
          armed: Boolean(next.armed),
          mode: next.mode === 'autonomous' ? 'autonomous' : 'manual',
          throttle: clamp(Math.round(next.throttle || 0), -200, 200),
          steer: clamp(Math.round(next.steer || 0), -200, 200),
          navigation: nav,
        };
        lastCommandAt = Date.now();
      } else if (next.type === 'release') {
        // 投放释放：仅需连接在线即可触发，不要求解锁（救援动作本身就是目的）。
        // 由服务端强制下发 mission_state=2 且停船。
        if (serialReady) {
          releaseUntil = Date.now() + RELEASE_HOLD_MS;
          console.log('[release] 触发投放释放');
          broadcast({ type: 'release', active: true, at: Date.now() });
        } else {
          broadcast({ type: 'error', message: '未连接串口，无法触发投放' });
        }
      }
    } catch {}
  });
  socket.on('close', () => clients.delete(socket));
});

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function validNavigation(value) {
  return value && ['boatX', 'boatY', 'heading', 'targetX', 'targetY']
    .every((key) => Number.isFinite(value[key])) &&
    [value.boatX, value.boatY, value.targetX, value.targetY].every((coordinate) => coordinate >= 0 && coordinate <= 1.2) &&
    value.heading >= 0 && value.heading < 360;
}

function encodeCommand() {
  // 释放优先级最高：覆盖 mission_state=2 且停船，持续到时间窗结束。
  if (releaseActive()) {
    return encodeGroundToBoat(command, true, { missionState: 2, releaseFlag: 1 });
  }

  // 视觉定位优先：只要 Python 程序还在持续推送，就以它为准进入自主航行。
  // 这样网页不需要（也无法）手动填坐标，且 vision 停推后 400 ms 内自动交还控制权。
  if (visionNavFresh()) {
    return encodeGroundToBoat(
      { armed: true, mode: 'autonomous', throttle: 0, steer: 0, navigation: visionNav },
      true,
    );
  }

  const active = command.armed && Date.now() - lastCommandAt < 250;
  // 不再因为"自主模式没有坐标"而退化为待命：
  // navigation 为 null 时，encodeGroundToBoat 依然发 mission_state=1，
  // 船端据此进入纯二哈视觉搜救。
  return encodeGroundToBoat(command, active);
}

function parseTelemetry(chunk) {
  rx = Buffer.concat([rx, chunk]);
  while (rx.length >= 35) {
    const start = rx.indexOf(Buffer.from([0x5a, 0xa5]));
    if (start < 0) {
      rx = rx.subarray(Math.max(0, rx.length - 1));
      return;
    }
    if (start > 0) rx = rx.subarray(start);
    if (rx.length < 35) return;
    const payload = rx.subarray(2, 34);
    let checksum = 0;
    for (const byte of payload) checksum = (checksum + byte) & 0xff;
    if (rx[34] !== checksum) {
      rx = rx.subarray(1);
      continue;
    }
    telemetry = {
      heading: payload.readFloatLE(0),
      leftMotor: payload.readInt32LE(4),
      rightMotor: payload.readInt32LE(8),
      targetDetected: payload.readUInt8(12) !== 0,
      targetX: payload.readInt32LE(16),
      targetY: payload.readInt32LE(20),
      distance: payload.readFloatLE(24),
      emergency: payload.readUInt8(28) !== 0,
      receivedAt: Date.now(),
    };
    rx = rx.subarray(35);
    broadcast({ type: 'telemetry', telemetry });
  }
}

function broadcast(message) {
  const serialized = JSON.stringify(message);
  for (const client of clients) if (client.readyState === 1) client.send(serialized);
}

/**
 * 命令下发循环（20 Hz）。
 *
 * 关键：原来这里写的是 `if (serial?.isOpen) serial.write(...)`，没有回调 ——
 * 而 serialport 的 write 在链路失效时通过**回调**报 "Port is not open"，
 * 不传回调这个错误就被完全吞掉：界面显示已连接、实际一条指令都没发出去。
 * 现在显式处理回调，并在连续失败时把状态置回未连接，让界面能如实反映。
 */
let consecutiveWriteFailures = 0;

setInterval(() => {
  if (!serialReady || !serial) return;

  serial.write(encodeCommand(), (error) => {
    if (!error) {
      consecutiveWriteFailures = 0;
      return;
    }

    consecutiveWriteFailures++;
    serialReady = false;   // 立刻置为不可用，避免继续无效写入

    if (consecutiveWriteFailures === 1) {
      console.error(`[serial] 写入失败: ${error.message}`);
      broadcast({ type: 'error', message: `串口写入失败: ${error.message}，请重新连接` });
      broadcast({ type: 'connection', connected: false, port: serial?.path ?? null });
    }
  });
}, 50);

server.listen(port, host, () => console.log(`Boat control bridge listening on http://${host}:${port}`));

