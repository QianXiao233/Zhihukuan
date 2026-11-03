import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Anchor, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, CircleStop, Compass, Crosshair, Gamepad2, Maximize, Radio, RefreshCw, Shield, Waves, Wifi, WifiOff, Zap } from 'lucide-react';
import Janus from 'janus-gateway';
import adapterPackage from 'webrtc-adapter';

// The Janus browser bundle expects the adapter shim as a global dependency.
globalThis.adapter = adapterPackage?.default ?? adapterPackage;

// ---------------------------------------------------------------------------
// 桥接服务地址（serial-service，默认本机 4174 端口）。
//
// 驾驶台现在作为水库平台的 /console/ 子应用被 iframe 嵌入，桥接板可能不在
// 平台所在的机器上，因此地址支持通过 URL query 覆盖：
//
//   /console/index.html?api=http://192.168.2.14:4174
//
// 规则：
//   * 只接受 http / https 的绝对地址，其余（空值、ftp:、javascript:、乱写）一律回退默认；
//   * WebSocket 地址由 http→ws、https→wss 推导，路径与 HTTP 基地址保持一致；
//   * 默认仍指向本机，单独打开 index.html 时行为不变。
// ---------------------------------------------------------------------------
const DEFAULT_API_HTTP = 'http://127.0.0.1:4174';

const deriveWsUrl = (httpUrl) => {
  const url = new URL(httpUrl);
  const protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${url.host}${url.pathname}`.replace(/\/+$/, '');
};

const resolveBoatEndpoints = () => {
  const fallback = { api: DEFAULT_API_HTTP, ws: deriveWsUrl(DEFAULT_API_HTTP) };
  try {
    const raw = new URLSearchParams(window.location.search).get('api');
    if (!raw) return fallback;
    const candidate = new URL(raw.trim());
    if (candidate.protocol !== 'http:' && candidate.protocol !== 'https:') return fallback;
    // 只保留 origin + path（去掉 query/hash 和结尾斜杠），避免拼出 `//api/ports`
    const api = `${candidate.origin}${candidate.pathname}`.replace(/\/+$/, '');
    return { api, ws: deriveWsUrl(api) };
  } catch {
    return fallback;
  }
};

const { api: API, ws: WS_URL } = resolveBoatEndpoints();

/**
 * Janus 视频网关地址同样可配置。
 *
 * 为什么必须可配：默认是船载 WiFi 模块的局域网地址（http://192.168.2.14:8088/janus）。
 * 平台以 HTTPS 部署时，浏览器会把 http:// 的视频信令当成混合内容直接拦掉——所以
 * 需要能传一个 https/wss 的反代地址（janus-gateway 会自动按 https 走 wss）。
 * 用法：/console/index.html?janus=https://boat.example.com/janus
 */
const DEFAULT_JANUS = 'http://192.168.2.14:8088/janus';

const resolveJanusUrl = () => {
  try {
    const raw = new URLSearchParams(window.location.search).get('janus');
    if (!raw) return DEFAULT_JANUS;
    const candidate = new URL(raw.trim());
    if (candidate.protocol !== 'http:' && candidate.protocol !== 'https:') return DEFAULT_JANUS;
    return `${candidate.origin}${candidate.pathname}`.replace(/\/+$/, '');
  } catch {
    return DEFAULT_JANUS;
  }
};

const JANUS = resolveJanusUrl();

// 便于在浏览器控制台核对本次实际生效的桥接/视频地址（排查"连不上"时不用猜）
if (typeof window !== 'undefined') {
  window.__BOAT_CONSOLE_ENDPOINTS__ = { api: API, ws: WS_URL, janus: JANUS };
}

const STREAM_ID = 99;
const keys = { w: 'forward', a: 'left', s: 'reverse', d: 'right' };

// 与 serial-service / protocol.js 保持一致的量程
const POOL_SIZE_M = 1.2;
const HEADING_MAX = 359.9;        // 服务端要求 heading < 360，这里留一位小数
// 船端 20Hz 上报；超过这个时间没收到就认为遥测断了（桥接板/串口/船端任一环）
const TELEMETRY_TIMEOUT_MS = 1500;
// "已下发"只是"帧发出去了"，不是船端确认；6 秒后复位按钮，避免一直挂着假状态
const RELEASE_STATUS_MS = 6000;

export function App() {
  const [ports, setPorts] = useState([]);
  // 初始为空：真实端口由 /api/ports 填入后自动选择，不写死任何 COM 号
  const [selectedPort, setSelectedPort] = useState('');
  const [connected, setConnected] = useState(false);
  const [armed, setArmed] = useState(false);
  const [controlMode, setControlMode] = useState('manual');
  const [navigation, setNavigation] = useState({ boatX: '', boatY: '', heading: '', targetX: '', targetY: '' });
  const [pressed, setPressed] = useState({});
  const [telemetry, setTelemetry] = useState(null);
  const [videoState, setVideoState] = useState('idle');
  const [error, setError] = useState('');
  const [power, setPower] = useState(55);
  const [full, setFull] = useState(false);
  // 投放释放：两段式确认，避免误触（投放不可逆）
  const [releaseConfirm, setReleaseConfirm] = useState(false);
  const [releaseSentAt, setReleaseSentAt] = useState(null);
  // 视觉通道：谁在控制船，操作员必须看得见（否则"已锁定"可能是个假象）
  const [vision, setVision] = useState({ gate: true, active: false, ageMs: null });
  // 遥测是否超时（船端只在上报链路正常时才发状态，断了网页必须自己发现）
  const [telemetryStale, setTelemetryStale] = useState(false);
  const wsRef = useRef(null);
  const janusRef = useRef(null);
  const streamRef = useRef(null);
  const videoRef = useRef(null);
  const viewportRef = useRef(null);
  const pressedRef = useRef({});
  const armedRef = useRef(false);
  const connectedRef = useRef(false);
  const telemetryTimerRef = useRef(null);
  const releaseTimerRef = useRef(null);

  useEffect(() => { armedRef.current = armed; }, [armed]);
  useEffect(() => { connectedRef.current = connected; }, [connected]);
  useEffect(() => () => {
    window.clearTimeout(telemetryTimerRef.current);
    window.clearTimeout(releaseTimerRef.current);
  }, []);

  /** 每收到一帧遥测就重置看门狗；超时后由下面的 effect 自动锁定动力。 */
  const markTelemetry = useCallback(() => {
    setTelemetryStale(false);
    window.clearTimeout(telemetryTimerRef.current);
    telemetryTimerRef.current = window.setTimeout(
      () => setTelemetryStale(true),
      TELEMETRY_TIMEOUT_MS,
    );
  }, []);

  useEffect(() => {
    let active = true;
    fetch(`${API}/api/ports`).then((r) => r.json()).then((items) => {
      if (!active) return;
      setPorts(items);
      // 自动选中：优先 Espressif（ESP32）设备。
      // 注意：桥接板(ESP32-S3)与船载主控(ESP32-C3)的 USB VID/PID 完全相同
      // (303A:1001)，驱动层无法区分二者。所以只在"只有一个 Espressif 设备"时
      // 才敢自动选中；有两个及以上时必须由人指定，避免误连船载主控。
      const espressif = items.filter((item) => item.isEspressif);
      if (espressif.length === 1) setSelectedPort(espressif[0].path);
      else if (espressif.length === 0 && items[0]) setSelectedPort(items[0].path);
    }).catch(() => setError('本地串口服务未启动'));
    return () => { active = false; };
  }, []);

  useEffect(() => {
    let disposed = false;
    let retryTimer = null;
    let ws = null;

    const connect = () => {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === 'connection') {
          setConnected(Boolean(message.connected));
          if (!message.connected) {
            setArmed(false);
            // 断开时清掉看门狗，避免"离线 + 遥测超时"两条提示同时挂
            window.clearTimeout(telemetryTimerRef.current);
            setTelemetryStale(false);
          } else {
            // 串口一连上就开始看门狗：即使一帧遥测都没来，1.5 s 后也要报超时
            markTelemetry();
          }
          if (message.telemetry) setTelemetry(message.telemetry);
          if (message.vision) setVision(message.vision);
        }
        if (message.type === 'telemetry') {
          setTelemetry(message.telemetry);
          markTelemetry();
        }
        if (message.type === 'vision') setVision(message);
        if (message.type === 'release') {
          setReleaseSentAt(message.at ?? Date.now());
          setReleaseConfirm(false);
          // 释放没有回执，界面不能一直显示"已下发"
          window.clearTimeout(releaseTimerRef.current);
          releaseTimerRef.current = window.setTimeout(() => setReleaseSentAt(null), RELEASE_STATUS_MS);
        }
        if (message.type === 'error') setError(message.message);
      };
      ws.onclose = () => {
        setConnected(false);
        setArmed(false);
        setVision((current) => ({ ...current, active: false }));
        window.clearTimeout(telemetryTimerRef.current);
        setTelemetryStale(false);
        // 断线自动重连：原来断开后只能刷新页面，操作员容易误以为船还在线
        if (!disposed) retryTimer = window.setTimeout(connect, 1500);
      };
    };

    connect();
    return () => {
      disposed = true;
      window.clearTimeout(retryTimer);
      ws?.close();
    };
  }, [markTelemetry]);

  /**
   * 投放释放（不可逆动作）。
   *
   * 两段式确认：第一次点击进入"确认"状态，再点一次才真正下发；
   * 3 秒内没有确认就自动取消，避免误触后一直挂着待确认状态。
   *
   * 注意：释放**不要求先解锁动力**。它是救援动作本身的目的，
   * 且服务端会强制 mission_state=2 并停船，不会与推进输出冲突。
   */
  const triggerRelease = () => {
    if (!connected) return;
    if (!releaseConfirm) {
      setReleaseConfirm(true);
      setError('');
      window.setTimeout(() => setReleaseConfirm(false), 3000);
      return;
    }
    setReleaseConfirm(false);
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'release' }));
    }
  };

  /**
   * 停止 / 锁定动力。
   *
   * lockVision=true 用于**明确的急停动作**（空格、ESC、红色急停、锁定动力、
   * 停止自主导航）：除了把网页通道归零，还会关闭服务端的"视觉接管闸门"。
   * 否则视觉程序在跑时，网页发出的 armed:false 会被服务端用强制 armed:true
   * 的视觉帧覆盖——红色急停按下去船还在跑。
   *
   * 失焦 / 切模式只归零网页通道，不动闸门：避免操作员切个窗口就把正在执行的
   * 视觉救援打断（要中断请用急停）。
   */
  const stopDrive = useCallback((lockVision = false) => {
    pressedRef.current = {};
    setPressed({});
    setArmed(false);
    armedRef.current = false;
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'command', armed: false, throttle: 0, steer: 0 }));
      if (lockVision) {
        wsRef.current.send(JSON.stringify({ type: 'visionGate', allow: false }));
        setVision((current) => ({ ...current, gate: false, active: false }));
      }
    }
  }, []);

  /** 重新允许视觉程序接管（急停之后必须由人显式恢复）。 */
  const allowVision = useCallback(() => {
    setError('');
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'visionGate', allow: true }));
      setVision((current) => ({ ...current, gate: true }));
    }
  }, []);

  // 遥测超时 = 船端/桥接板/串口至少有一环断了：立刻锁定动力并醒目提示。
  // （船端的 emergency 标志只在通信中断时置位，而那时它本身就不上报，所以
  //   网页不能依赖 emergency 字段，必须有本地的遥测看门狗。）
  useEffect(() => {
    if (!telemetryStale) return;
    setError('遥测超时：超过 1.5 秒未收到船端数据，已自动锁定网页动力');
    if (armedRef.current) {
      armedRef.current = false;
      setArmed(false);
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: 'command', armed: false, throttle: 0, steer: 0 }));
      }
    }
  }, [telemetryStale]);

  useEffect(() => {
    const send = () => {
      const current = pressedRef.current;
      const throttle = (current.forward ? 1 : 0) - (current.reverse ? 1 : 0);
      // 符号约定与固件/视觉一致：**正 steer = 右转**。
      // 固件 handle_manual 是 left = throttle + steer，左轮加速 -> 船头右偏，
      // 视觉伺服也用同一套约定（目标偏右 -> correction>0 -> 左轮加速）。
      // 原来这里写成 left-right，按 A 会右转，和界面/视觉的方向语义相反。
      const steer = (current.right ? 1 : 0) - (current.left ? 1 : 0);
      if (wsRef.current?.readyState !== WebSocket.OPEN) return;

      // 全部留空 -> 发 null，让船端进入"纯二哈视觉搜救"。
      // 注意不能用 Number('') —— 那会得到 0，船端会误判为有效坐标。
      const empty = Object.values(navigation).every((value) => value === '');
      // 全 0 是"没有定位"的约定值：船端会按无效处理、切到二哈搜救。
      // 网页若还宣称"坐标导航"就会误导操作员，所以这里同样判为无效。
      const allZero = !empty && Object.values(navigation).every((value) => Number(value) === 0);
      const validNavigation = !empty && !allZero && Object.entries(navigation).every(
        ([key, value]) => value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 &&
                          Number(value) <= (key === 'heading' ? HEADING_MAX : POOL_SIZE_M)
      );

      wsRef.current.send(JSON.stringify({
        type: 'command',
        // 自主模式下即使坐标为 null 也要 armed，
        // 否则服务端认为未激活，船端收到的仍是待命
        armed: armedRef.current && (controlMode === 'manual' || validNavigation || (controlMode === 'autonomous' && empty)),
        mode: controlMode,
        navigation: validNavigation
          ? Object.fromEntries(Object.entries(navigation).map(([key, value]) => [key, Number(value)]))
          : null,
        throttle: controlMode === 'manual' ? throttle * power * 2 : 0,
        steer: controlMode === 'manual' ? steer * power * 2 : 0,
      }));
    };
    const interval = window.setInterval(send, 50);
    return () => window.clearInterval(interval);
  }, [controlMode, navigation, power]);

  useEffect(() => {
    const isTyping = () => ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName);
    const down = (event) => {
      const key = event.key.toLowerCase();
      // ESC 始终急停；空格只在非输入状态下急停（否则在坐标框里按空格会误触发）。
      if (key === 'escape' || (key === ' ' && !isTyping())) {
        event.preventDefault();
        stopDrive(true);          // 明确急停：连视觉接管一起切断
        return;
      }
      if (!(key in keys) || isTyping()) return;
      event.preventDefault();
      if (controlMode !== 'manual' || !connectedRef.current || !armedRef.current) return;
      const next = { ...pressedRef.current, [keys[key]]: true };
      pressedRef.current = next;
      setPressed(next);
    };
    const up = (event) => {
      const key = event.key.toLowerCase();
      if (!(key in keys)) return;
      const next = { ...pressedRef.current, [keys[key]]: false };
      pressedRef.current = next;
      setPressed(next);
    };
    const onBlur = () => stopDrive();   // 失焦只停网页通道，不切断视觉救援
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', onBlur);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', onBlur);
      stopDrive();
    };
  }, [controlMode, stopDrive]);

  const connectSerial = async () => {
    setError('');
    // 串口号不再写死。只做一次轻量提示：选了非 Espressif 设备时提醒可能选错。
    // （桥接板与船载主控的 VID/PID 相同，无法程序化区分，只能靠提示引导。）
    const target = ports.find((item) => item.path === selectedPort);
    if (target && !target.isEspressif) {
      setError(`${selectedPort} 不是 ESP32 设备，桥接板通常显示为 USB 串行设备`);
      return;
    }
    try {
      const response = await fetch(`${API}/api/connect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ port: selectedPort }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '串口连接失败');
      setConnected(true);
      setArmed(false);
    } catch (cause) { setError(cause.message); }
  };

  const disconnectSerial = async () => {
    stopDrive();
    await fetch(`${API}/api/disconnect`, { method: 'POST' }).catch(() => {});
    setConnected(false);
  };

  /**
   * 自主模式有两种行为，由"是否填了坐标"决定：
   *   - 填了坐标 -> 坐标导航（依赖电脑 UVC 全局定位）
   *   - 没填坐标 -> 纯二哈视觉搜救：原地旋转搜索，识别到目标就自主前往，
   *                 估算距离 <= 20 cm 停车。完全不需要电脑定位。
   * 所以自主模式下**允许坐标为空**，不再强制校验。
   */
  const autonomousFieldsEmpty = Object.values(navigation).every((value) => value === '');
  const autonomousFieldsComplete = Object.values(navigation).every(
    (value) => value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0
  );
  const autonomousFieldsInRange = Object.entries(navigation).every(
    ([key, value]) => Number(value) <= (key === 'heading' ? HEADING_MAX : POOL_SIZE_M)
  );
  // 全 0 在船端是"没有定位"（会切到二哈搜救），不能当作坐标导航启动
  const autonomousFieldsAllZero = !autonomousFieldsEmpty
    && Object.values(navigation).every((value) => Number(value) === 0);

  const armDrive = () => {
    if (!connected) return;
    if (controlMode === 'autonomous') {
      // 要么全部留空（走二哈搜救），要么全部填写且合法；部分填写视为错误
      if (!autonomousFieldsEmpty && !(autonomousFieldsComplete && autonomousFieldsInRange)) {
        setError(`坐标请全部留空（二哈自主搜救）或全部填写合法值：X/Y 为 0–${POOL_SIZE_M} 米，航向 0–${HEADING_MAX} 度`);
        return;
      }
      if (autonomousFieldsAllZero) {
        setError('坐标不能全为 0：船端会把全 0 当作"没有定位"并切到二哈搜救。若想走二哈搜救请把坐标清空。');
        return;
      }
    }
    setError('');
    setArmed(true);
    armedRef.current = true;
  };

  const changeControlMode = (nextMode) => {
    stopDrive();
    setError('');
    setControlMode(nextMode);
  };

  const updateNavigation = (key, value) => setNavigation((current) => ({ ...current, [key]: value }));

  const emergencyStop = () => { stopDrive(true); setError('急停已触发：动力输出归零，视觉接管已切断'); };

  const startStream = () => {
    setVideoState('connecting');
    Janus.init({ debug: false, callback: () => {
      if (!Janus.isWebrtcSupported()) { setVideoState('error'); setError('当前浏览器不支持 WebRTC'); return; }
      const janus = new Janus({
        server: [JANUS],
        iceServers: [{ urls: 'stun:stun.l.google.com:19302' }],
        success: () => janus.attach({
          plugin: 'janus.plugin.streaming',
          success: (handle) => { streamRef.current = handle; handle.send({ message: { request: 'watch', id: STREAM_ID } }); },
          onmessage: (message, jsep) => {
            if (!jsep) return;
            streamRef.current?.createAnswer({ jsep, media: { audioSend: false, videoSend: false }, success: (answer) => streamRef.current?.send({ message: { request: 'start' }, jsep: answer }), error: (cause) => { setVideoState('error'); setError(`WebRTC 协商失败：${cause}`); } });
          },
          onremotetrack: (track, _mid, on) => {
            if (!on || track.kind !== 'video') return;
            const media = new MediaStream([track]);
            if (videoRef.current) { videoRef.current.srcObject = media; videoRef.current.play().catch(() => {}); }
            setVideoState('live');
          },
          oncleanup: () => { if (videoRef.current) videoRef.current.srcObject = null; setVideoState('idle'); },
          error: (cause) => { setVideoState('error'); setError(`视频插件连接失败：${cause}`); },
        }),
        error: (cause) => { setVideoState('error'); setError(`Janus 连接失败：${cause}`); },
        destroyed: () => setVideoState('idle'),
      });
      janusRef.current = janus;
    } });
  };

  const stopStream = () => {
    streamRef.current?.send({ message: { request: 'stop' } });
    janusRef.current?.destroy();
    janusRef.current = null;
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setVideoState('idle');
  };

  useEffect(() => () => { janusRef.current?.destroy(); }, []);

  const toggleFullscreen = () => {
    if (!document.fullscreenElement) viewportRef.current?.requestFullscreen?.().then(() => setFull(true));
    else document.exitFullscreen().then(() => setFull(false));
  };

  const axes = {
    forward: Boolean(pressed.forward),
    reverse: Boolean(pressed.reverse),
    left: Boolean(pressed.left),
    right: Boolean(pressed.right),
  };
  const throttle = (axes.forward ? 1 : 0) - (axes.reverse ? 1 : 0);
  const steer = (axes.left ? 1 : 0) - (axes.right ? 1 : 0);
  const heading = Number.isFinite(telemetry?.heading) && telemetry.heading >= 0 && telemetry.heading <= 360 ? telemetry.heading : null;
  const speed = telemetry ? Math.round((Math.abs(telemetry.leftMotor) + Math.abs(telemetry.rightMotor)) / 4) : Math.round(Math.max(Math.abs(throttle), Math.abs(steer)) * power);
  const direction = axes.forward && axes.left ? '左前' : axes.forward && axes.right ? '右前' : axes.reverse && axes.left ? '左后' : axes.reverse && axes.right ? '右后' : axes.forward ? '前进' : axes.reverse ? '倒车' : axes.left ? '左转' : axes.right ? '右转' : '待命';
  const videoLive = videoState === 'live';

  return <main className="console-shell">
    <header className="topbar">
      <a className="brand" href="#" aria-label="智护库安首页"><span className="brand-mark"><Anchor size={18} /></span><span>智护库安</span><i /></a>
      <div className="top-status"><span className={connected ? 'status-dot on' : 'status-dot'} />{connected ? `串口在线 · ${selectedPort}` : '串口未连接'}<span className="divider" /><span className={vision.active ? 'status-dot on' : 'status-dot'} /><span className={vision.active ? 'vision-state active' : 'vision-state'}>{vision.active ? '视觉接管中' : vision.gate ? '视觉待机' : '视觉已屏蔽'}</span>{!vision.gate && <button className="vision-resume" onClick={allowVision} title="重新允许 locator.py 的坐标接管船">恢复视觉</button>}<span className="divider" /><Waves size={14} className={videoLive ? 'live-icon' : ''} />{videoLive ? '视频实时' : '视频待连接'}</div>
      <button className="header-stop" onClick={emergencyStop} title="立即切断控制输出"><CircleStop size={16} />急停 <kbd>SPACE</kbd></button>
    </header>

    <div className="main-grid">
      <section className="visual-column">
        <div className="video-shell" ref={viewportRef}>
          <video className="remote-video" ref={videoRef} autoPlay playsInline muted />
          {!videoLive && <div className="video-placeholder"><div className="radar"><span /><span /><Crosshair size={30} /></div><div className="feed-label">{videoState === 'connecting' ? '正在建立 WebRTC 连接' : videoState === 'error' ? '视频连接异常' : '摄像头信号待接入'}</div><div className="feed-ip">192.168.2.14 <span>/</span> Janus Stream 99</div><button className="stream-button" onClick={videoLive ? stopStream : startStream}>{videoState === 'connecting' ? <RefreshCw size={15} className="spin" /> : <Camera size={15} />}{videoState === 'connecting' ? '连接中' : '接入实时画面'}</button></div>}
          <div className="video-vignette" />
          <div className="video-topline"><span className="video-tag"><span className={videoLive ? 'status-dot on' : 'status-dot'} />{videoLive ? 'LIVE' : 'CAM 01'}</span><span className="video-resolution">1920 × 1080 <i>·</i> 30 FPS</span></div>
          <div className="crosshair"><span /><span /></div>
          <div className="video-bottomline"><span><Radio size={13} />{videoLive ? 'WEBRTC · 99' : 'AWAITING SIGNAL'}</span><div className="video-actions">{videoLive && <button onClick={stopStream} title="断开实时画面"><WifiOff size={14} /></button>}<button onClick={toggleFullscreen} title={full ? '退出全屏' : '全屏'}><Maximize size={15} /></button></div></div>
        </div>
        <div className="telemetry-strip">
          <div className="metric direction-metric"><span className="metric-label"><Activity size={13} />操作方向</span><strong>{direction}</strong><small>{armed ? 'WASD 手动控制' : '控制未解锁'}</small></div>
          <div className="metric"><span className="metric-label"><Compass size={13} />船头航向</span><strong>{heading !== null ? `${Math.round((heading + 360) % 360).toString().padStart(3, '0')}°` : '---°'}</strong><small>{heading !== null ? '船端回传' : '当前固件无罗盘'}</small></div>
          <div className="metric"><span className="metric-label"><Crosshair size={13} />目标识别</span><strong className={telemetry?.targetDetected ? 'target-found' : ''}>{telemetry?.targetDetected ? '已锁定' : '未检测'}</strong><small>{telemetry?.targetDetected && Number.isFinite(telemetry?.distance) ? `${telemetry.distance.toFixed(2)} m` : 'HUSKYLENS'}</small></div>
          <div className="metric"><span className="metric-label"><Wifi size={13} />通信状态</span><strong className={(telemetry?.emergency || telemetryStale) ? 'warn' : connected ? 'good' : ''}>{telemetry?.emergency ? '应急' : telemetryStale ? '遥测超时' : connected ? '稳定' : '离线'}</strong><small>{telemetryStale ? '超过 1.5 s 无数据' : 'ESP-NOW · CH 1'}</small></div>
        </div>
      </section>

      <aside className="pilot-column">
        <div className="pilot-heading"><div><h1>驾驶控制</h1><p>{controlMode === 'manual' ? 'WASD · 按住驱动，松开即停' : (autonomousFieldsEmpty ? '二哈自主搜救 · 识别到目标即自行前往' : '坐标导航 · 进入目标区域后二哈接管')}</p></div><span className="mode-icon"><Gamepad2 size={18} /></span></div>

        <div className="mode-panel"><div className="panel-title"><span><Activity size={14} />控制模式</span><span className={armed ? 'connection-state on' : 'connection-state'}>{armed ? '运行中' : '已锁定'}</span></div><div className="mode-switch"><button className={controlMode === 'manual' ? 'selected' : ''} aria-pressed={controlMode === 'manual'} onClick={() => changeControlMode('manual')}>手动</button><button className={controlMode === 'autonomous' ? 'selected' : ''} aria-pressed={controlMode === 'autonomous'} onClick={() => changeControlMode('autonomous')}>自主</button></div></div>

        {controlMode === 'autonomous' && <div className="navigation-panel"><div className="panel-title"><span><Crosshair size={14} />导航坐标 · 米 / 度</span><span className="connection-state">{autonomousFieldsEmpty ? '可留空' : '上位机定位'}</span></div><div className="coordinate-grid">
          <CoordinateInput label="船 X" value={navigation.boatX} onChange={(value) => updateNavigation('boatX', value)} />
          <CoordinateInput label="船 Y" value={navigation.boatY} onChange={(value) => updateNavigation('boatY', value)} />
          <CoordinateInput label="航向" value={navigation.heading} onChange={(value) => updateNavigation('heading', value)} />
          <CoordinateInput label="目标 X" value={navigation.targetX} onChange={(value) => updateNavigation('targetX', value)} />
          <CoordinateInput label="目标 Y" value={navigation.targetY} onChange={(value) => updateNavigation('targetY', value)} />
        </div><small className="navigation-note">{autonomousFieldsEmpty
          ? '坐标留空 = 纯二哈视觉搜救：船原地旋转搜索，识别到目标后自主前往，估算距离 ≤ 20 cm 停车。不需要电脑定位，直接点下方按钮即可启动。'
          : '已填写坐标 = 坐标导航：需电脑持续提供全局定位（UVC 相机），进入目标 40 cm 内后由二哈接管。注意目前尚未接入相机定位，静态值仅适合台架验证。'}</small></div>}
        <div className="speed-panel"><div className="speed-caption"><span>推进功率</span><span className={speed ? 'speed-active' : ''}>{speed}<small>%</small></span></div><div className="speed-gauge"><div className="speed-fill" style={{ width: `${Math.min(100, speed)}%` }} /><div className="speed-ticks">{Array.from({ length: 11 }, (_, i) => <i key={i} />)}</div></div><div className="speed-foot"><span>0</span><span>MAX 100</span></div></div>

        <div className="heading-panel"><div className="panel-title"><span><Compass size={14} />当前方向</span><span className="heading-readout">{heading !== null ? `${Math.round((heading + 360) % 360).toString().padStart(3, '0')}°` : '---°'}</span></div><div className="compass-line"><span>N</span><i className={axes.left ? 'turn-left' : axes.right ? 'turn-right' : ''}><ArrowUp size={17} /></i><span>S</span><div className="compass-scale"><b /><b /><b /><b /><b /><b /><b /><b /><b /></div></div><div className="current-direction"><span className={armed ? 'mini-dot on' : 'mini-dot'} />{direction}<em>{heading !== null ? '实时航向回传' : '等待姿态传感器'}</em></div></div>

        {controlMode === 'manual' && <div className="drive-panel"><div className="panel-title"><span><Gamepad2 size={14} />方向控制</span><span className="keys-hint">W A S D</span></div><div className="keypad"><span /><KeyButton label="W" icon={<ArrowUp size={19} />} active={axes.forward} onDown={() => { if (armed) { const n = { ...pressedRef.current, forward: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, forward: false }; pressedRef.current = n; setPressed(n); }} /><span /><KeyButton label="A" icon={<ArrowLeft size={19} />} active={axes.left} onDown={() => { if (armed) { const n = { ...pressedRef.current, left: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, left: false }; pressedRef.current = n; setPressed(n); }} /><KeyButton label="S" icon={<ArrowDown size={19} />} active={axes.reverse} onDown={() => { if (armed) { const n = { ...pressedRef.current, reverse: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, reverse: false }; pressedRef.current = n; setPressed(n); }} /><KeyButton label="D" icon={<ArrowRight size={19} />} active={axes.right} onDown={() => { if (armed) { const n = { ...pressedRef.current, right: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, right: false }; pressedRef.current = n; setPressed(n); }} /></div><div className="drive-state"><span className={armed ? 'mini-dot on' : 'mini-dot'} />{armed ? '手动控制已解锁' : '待机中'}</div><button className={armed ? 'arm-button armed' : 'arm-button'} disabled={!connected} onClick={armed ? () => stopDrive(true) : armDrive}><Shield size={15} />{armed ? '锁定动力' : connected ? '解锁驾驶' : '请先连接设备'}</button></div>}

        {controlMode === 'autonomous' && <div className="drive-panel autonomous-start"><div className="drive-state"><span className={armed ? 'mini-dot on' : 'mini-dot'} />{armed ? (autonomousFieldsEmpty ? '二哈自主搜救中 · 已持续下发' : '自主导航指令持续下发') : '待机中'}</div><button className={armed ? 'arm-button armed' : 'arm-button'} disabled={!connected} onClick={armed ? () => stopDrive(true) : armDrive}><Shield size={15} />{armed ? '停止自主导航' : connected ? (autonomousFieldsEmpty ? '开始二哈自主搜救' : '开始自主导航') : '请先连接设备'}</button></div>}

        {controlMode === 'manual' && <div className="power-control"><div className="power-label"><span><Zap size={14} />最大动力</span><b>{power}%</b></div><input aria-label="最大动力" type="range" min="20" max="100" step="5" value={power} onChange={(e) => setPower(Number(e.target.value))} /></div>}

        <div className="release-panel">
          <div className="panel-title">
            <span><Anchor size={14} />投放释放</span>
            <span className="connection-state">
              {releaseSentAt !== null ? '已下发' : '待命'}
            </span>
          </div>
          <button
            className={releaseConfirm ? 'release-button confirm' : 'release-button'}
            disabled={!connected}
            onClick={triggerRelease}
          >
            <Anchor size={15} />
            {!connected
              ? '请先连接设备'
              : releaseConfirm
                ? '再点一次确认投放（不可撤销）'
                : '投放救生圈'}
          </button>
          <small className="release-note">
            触发后舵机拉出插销、保持 500 ms 后回位，动作期间自动停船，需二次确认防误触。
            {releaseSentAt !== null
              ? ' 已下发，请以船端串口日志的「释放 N」与舵机动作为准。'
              : ''}
          </small>
        </div>

        <div className="connection-panel"><div className="connection-top"><span><Radio size={14} />串口桥接板</span><span className={connected ? 'connection-state on' : 'connection-state'}>{connected ? '已连接' : '断开'}</span></div><div className="connection-controls"><select aria-label="串口设备" value={selectedPort} onChange={(e) => setSelectedPort(e.target.value)} disabled={connected}>{ports.length ? <>{!ports.some((item) => item.path === selectedPort) && <option value={selectedPort}>{selectedPort}</option>}{ports.map((item) => <option key={item.path} value={item.path}>{item.path}{item.isEspressif ? ' · ESP32' : ''}{item.friendlyName && !item.isEspressif ? ` · ${item.friendlyName}` : ''}</option>)}</> : <option value={selectedPort}>{selectedPort || '未发现端口'}</option>}</select><button onClick={connected ? disconnectSerial : connectSerial} className={connected ? 'connect-button connected' : 'connect-button'}>{connected ? <><WifiOff size={14} />断开</> : <><Wifi size={14} />连接</>}</button></div>{ports.filter((p) => p.isEspressif).length > 1 && !connected && <div className="error-line" role="status">检测到多个 ESP32 设备（桥接板与船载主控的 USB 标识相同，无法自动区分）：请选择桥接板所在的端口，船载主控端口连接后不会有遥测。</div>}{error && <div className="error-line" role="status">{error}</div>}</div>
      </aside>
    </div>
    <footer className="footer"><span><Waves size={14} />智护库安 · 微型水上自主搜救艇</span><span><span className="mini-dot on" />安全控制已启用</span><span>ESP32-S3 串口桥 · 115200 baud</span></footer>
  </main>;
}

function KeyButton({ label, icon, active, onDown, onUp }) {
  return <button className={active ? 'key active' : 'key'} aria-label={`按住 ${label} 控制船艇`} onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); onDown(); }} onPointerUp={onUp} onPointerCancel={onUp} onLostPointerCapture={onUp} onContextMenu={(event) => event.preventDefault()}><span>{icon}</span><kbd>{label}</kbd></button>;
}

function CoordinateInput({ label, value, onChange }) {
  const isHeading = label === '航向';
  return <label className="coordinate-input">{label}<input type="number" inputMode="decimal" min="0" max={isHeading ? HEADING_MAX : POOL_SIZE_M} step={isHeading ? '1' : '0.01'} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}
