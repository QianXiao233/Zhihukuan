import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, Anchor, ArrowDown, ArrowLeft, ArrowRight, ArrowUp, Camera, CircleStop, Compass, Crosshair, Gamepad2, Maximize, Radio, RefreshCw, Shield, Waves, Wifi, WifiOff, Zap } from 'lucide-react';
import Janus from 'janus-gateway';
import adapterPackage from 'webrtc-adapter';

// The Janus browser bundle expects the adapter shim as a global dependency.
globalThis.adapter = adapterPackage?.default ?? adapterPackage;

const API = 'http://localhost:4174';
const JANUS = 'http://192.168.2.14:8088/janus';
const STREAM_ID = 99;
const keys = { w: 'forward', a: 'left', s: 'reverse', d: 'right' };

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
  const wsRef = useRef(null);
  const janusRef = useRef(null);
  const streamRef = useRef(null);
  const videoRef = useRef(null);
  const viewportRef = useRef(null);
  const pressedRef = useRef({});
  const armedRef = useRef(false);
  const connectedRef = useRef(false);

  useEffect(() => { armedRef.current = armed; }, [armed]);
  useEffect(() => { connectedRef.current = connected; }, [connected]);

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
    const ws = new WebSocket('ws://localhost:4174');
    wsRef.current = ws;
    ws.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === 'connection') {
        setConnected(Boolean(message.connected));
        if (!message.connected) setArmed(false);
        if (message.telemetry) setTelemetry(message.telemetry);
      }
      if (message.type === 'telemetry') setTelemetry(message.telemetry);
      if (message.type === 'release') {
        setReleaseSentAt(message.at ?? Date.now());
        setReleaseConfirm(false);
      }
      if (message.type === 'error') setError(message.message);
    };
    ws.onclose = () => { setConnected(false); setArmed(false); };
    return () => ws.close();
  }, []);

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

  const stopDrive = useCallback(() => {
    pressedRef.current = {};
    setPressed({});
    setArmed(false);
    armedRef.current = false;
    if (wsRef.current?.readyState === WebSocket.OPEN) wsRef.current.send(JSON.stringify({ type: 'command', armed: false, throttle: 0, steer: 0 }));
  }, []);

  useEffect(() => {
    const send = () => {
      const current = pressedRef.current;
      const throttle = (current.forward ? 1 : 0) - (current.reverse ? 1 : 0);
      const steer = (current.left ? 1 : 0) - (current.right ? 1 : 0);
      if (wsRef.current?.readyState !== WebSocket.OPEN) return;

      // 全部留空 -> 发 null，让船端进入"纯二哈视觉搜救"。
      // 注意不能用 Number('') —— 那会得到 0，船端会误判为有效坐标。
      const empty = Object.values(navigation).every((value) => value === '');
      const validNavigation = !empty && Object.entries(navigation).every(
        ([key, value]) => value !== '' && Number.isFinite(Number(value)) && Number(value) >= 0 &&
                          Number(value) <= (key === 'heading' ? 359.999 : 1.2)
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
    const down = (event) => {
      const key = event.key.toLowerCase();
      if (key === ' ' || key === 'escape') { event.preventDefault(); stopDrive(); return; }
      if (!(key in keys) || ['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return;
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
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', stopDrive);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', stopDrive);
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
    ([key, value]) => Number(value) <= (key === 'heading' ? 359.999 : 1.2)
  );

  const armDrive = () => {
    if (!connected) return;
    if (controlMode === 'autonomous') {
      // 要么全部留空（走二哈搜救），要么全部填写且合法；部分填写视为错误
      if (!autonomousFieldsEmpty && !(autonomousFieldsComplete && autonomousFieldsInRange)) {
        setError('坐标请全部留空（二哈自主搜救）或全部填写合法值：X/Y 为 0–1.2 米，航向 0–360 度');
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

  const emergencyStop = () => { stopDrive(); setError('急停已触发，动力输出归零'); };

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
      <div className="top-status"><span className={connected ? 'status-dot on' : 'status-dot'} />{connected ? `串口在线 · ${selectedPort}` : '串口未连接'}<span className="divider" /><Waves size={14} className={videoLive ? 'live-icon' : ''} />{videoLive ? '视频实时' : '视频待连接'}</div>
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
          <div className="metric"><span className="metric-label"><Crosshair size={13} />目标识别</span><strong className={telemetry?.targetDetected ? 'target-found' : ''}>{telemetry?.targetDetected ? '已锁定' : '未检测'}</strong><small>{telemetry?.targetDetected ? `${telemetry.distance.toFixed(2)} m` : 'HUSKYLENS'}</small></div>
          <div className="metric"><span className="metric-label"><Wifi size={13} />通信状态</span><strong className={telemetry?.emergency ? 'warn' : connected ? 'good' : ''}>{telemetry?.emergency ? '应急' : connected ? '稳定' : '离线'}</strong><small>ESP-NOW · CH 1</small></div>
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

        {controlMode === 'manual' && <div className="drive-panel"><div className="panel-title"><span><Gamepad2 size={14} />方向控制</span><span className="keys-hint">W A S D</span></div><div className="keypad"><span /><KeyButton label="W" icon={<ArrowUp size={19} />} active={axes.forward} onDown={() => { if (armed) { const n = { ...pressedRef.current, forward: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, forward: false }; pressedRef.current = n; setPressed(n); }} /><span /><KeyButton label="A" icon={<ArrowLeft size={19} />} active={axes.left} onDown={() => { if (armed) { const n = { ...pressedRef.current, left: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, left: false }; pressedRef.current = n; setPressed(n); }} /><KeyButton label="S" icon={<ArrowDown size={19} />} active={axes.reverse} onDown={() => { if (armed) { const n = { ...pressedRef.current, reverse: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, reverse: false }; pressedRef.current = n; setPressed(n); }} /><KeyButton label="D" icon={<ArrowRight size={19} />} active={axes.right} onDown={() => { if (armed) { const n = { ...pressedRef.current, right: true }; pressedRef.current = n; setPressed(n); } }} onUp={() => { const n = { ...pressedRef.current, right: false }; pressedRef.current = n; setPressed(n); }} /></div><div className="drive-state"><span className={armed ? 'mini-dot on' : 'mini-dot'} />{armed ? '手动控制已解锁' : '待机中'}</div><button className={armed ? 'arm-button armed' : 'arm-button'} disabled={!connected} onClick={armed ? stopDrive : armDrive}><Shield size={15} />{armed ? '锁定动力' : connected ? '解锁驾驶' : '请先连接设备'}</button></div>}

        {controlMode === 'autonomous' && <div className="drive-panel autonomous-start"><div className="drive-state"><span className={armed ? 'mini-dot on' : 'mini-dot'} />{armed ? (autonomousFieldsEmpty ? '二哈自主搜救中 · 已持续下发' : '自主导航指令持续下发') : '待机中'}</div><button className={armed ? 'arm-button armed' : 'arm-button'} disabled={!connected} onClick={armed ? stopDrive : armDrive}><Shield size={15} />{armed ? '停止自主导航' : connected ? (autonomousFieldsEmpty ? '开始二哈自主搜救' : '开始自主导航') : '请先连接设备'}</button></div>}

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
  return <label className="coordinate-input">{label}<input type="number" inputMode="decimal" min="0" max={isHeading ? 359.9 : 1.2} step={isHeading ? '1' : '0.01'} value={value} onChange={(event) => onChange(event.target.value)} /></label>;
}
