import * as THREE from 'three'

/**
 * 大坝水库数字人 —— 3D 悬浮机器人渲染器
 *
 * 依据《项目规格说明》第 6 章「数字人（3D 机器人）完整规格」1:1 重建：
 * 白色主体 + 蓝色发光、大圆头盔、黑色屏幕脸、胶囊形发光眼 + 微笑嘴、
 * 蓝色耳件、圆润分件装甲。风格：Q 版可爱但专业（科技感、不花哨）。
 */

/** 6.2 配色常量 */
export const ROBOT_COLORS = {
  /** 外壳：亮白，陶瓷质感（metalness 0.12，非金属） */
  shell: 0xf2f6fa,
  /** 发光：明亮科技蓝（眼、嘴、胸条、臂条、脚环、耳件） */
  glow: 0x2fa8ff,
  /** 屏幕：近黑（面部屏幕） */
  screen: 0x0a1220,
  /** 关节：深灰（肩/肘/髋/膝关节球） */
  joint: 0x2b3440,
  /** 屏幕内凹：更深的黑（屏幕底衬） */
  screenInner: 0x061020,
}

/** 分件缝线用的浅灰白（文档未指定，取外壳的同色系压暗） */
const COLOR_SEAM = 0xdbe4ee

/** 6.5 相机与比例 */
const CAMERA_POSITION = { x: 0, y: 0.16, z: 5.2 }
const CAMERA_FOV = 28
const ROOT_SCALE = 0.72
const HEAD_BASE_Y = 0.2233
const BODY_BASE_Y = -0.35
/** 地面效果所在高度 */
const GROUND_Y = -1.12

/** 6.6 动画参数 */
const FLOAT_FREQ = 1.1
const FLOAT_AMP = 0.035
/** 头部跟随同相位，幅度 ×1.35（惯性感） */
const HEAD_FOLLOW_FACTOR = 1.35
const SWAY_FREQ = 0.7
const SWAY_AMP = 0.016
/** 说话前倾角度 */
const LEAN_MAX = -0.055
const BLINK_MIN_INTERVAL = 2.6
const BLINK_INTERVAL_RANGE = 3.8
const BLINK_DURATION = 0.11
/** 眼睛 scale.y 最小保留值，不显得突兀 */
const EYE_MIN_SCALE = 0.08
/** 投影：浮越高 → 越大越淡 */
const SHADOW_OPACITY_NEAR = 0.34
const SHADOW_OPACITY_FAR = 0.18
const SHADOW_SCALE_NEAR = 1.0
const SHADOW_SCALE_FAR = 1.22
/** 光环脉动与自转 */
const RING_EMISSIVE_BASE = 1.2
const RING_EMISSIVE_AMP = 0.5
const RING_SPIN_SPEED = 0.25

/** ─────────── 肢体动作参数 ─────────── */

/**
 * 动作类型：待机 / 思考 / 说话 / 挥手 / 点头
 * @typedef {'idle' | 'thinking' | 'talking' | 'wave' | 'nod'} RobotGesture
 */

/** 一次性动作的持续时间（秒） */
const ONESHOT_DURATION = {
  wave: 1.9,
  nod: 1.4,
}

/** 各动作下手臂的目标姿态（弧度） */
const ARM_POSE = {
  /** 待机：自然下垂，轻微外张 */
  idle: { upper: 0.1, fore: 0.06 },
  /** 思考：一只手抬到脸侧 */
  thinking: { upper: -0.62, fore: -1.05 },
  /** 说话：轻微抬起做讲解手势 */
  talking: { upper: -0.34, fore: -0.5 },
}


/** 指数衰减插值，帧率无关的平滑趋近 */
function damp(current, target, lambda, dt) {
  return current + (target - current) * (1 - Math.exp(-lambda * dt))
}

export class RobotRenderer {
  /** @type {HTMLCanvasElement} */
  canvas
  /** @type {THREE.WebGLRenderer} */
  renderer
  /** @type {THREE.Scene} */
  scene
  /** @type {THREE.PerspectiveCamera} */
  camera
  clock = new THREE.Clock()

  /** 根节点，整体缩放 0.72 */
  root = new THREE.Group()
  /** 头部组 */
  head = new THREE.Group()
  /** 身体组 */
  body = new THREE.Group()
  /** 地面投影 */
  groundShadow
  shadowMaterial
  /** 地面发光环 */
  groundRing
  ringMaterial
  /** 眼睛（含各自的枢轴，便于压扁） */
  eyePivots = []
  eyes = []
  /** 嘴（含基准位置） */
  mouth
  mouthBaseY = 0
  /** 双臂枢轴：上臂绕 z 抬臂，肘部绕 z 屈肘 */
  armPivots = []

  /** 当前动作 */
  gesture = 'idle'
  /** 一次性动作剩余时间（挥手/点头） */
  oneshotRemain = 0
  oneshotKind = null
  /** 点头的独立相位，避免和身体浮动耦合 */
  nodPhase = 0

  /** 说话权重：0 闭合，1 全开（平滑过渡） */
  speakingAmount = 0
  speakingTarget = 0

  /** 眨眼状态机 */
  blinkCountdown = BLINK_MIN_INTERVAL + Math.random() * BLINK_INTERVAL_RANGE
  blinking = false
  blinkProgress = 0

  rafId = null
  running = false
  disposed = false

  // 复用材质
  shellMat
  seamMat
  glowMat
  screenMat
  screenInnerMat
  jointMat

  constructor(canvas, options = {}) {
    this.canvas = canvas
    const transparent = options.transparent ?? true

    // 渲染器：透明背景，输出 sRGB
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: transparent,
      antialias: true,
      premultipliedAlpha: false,
    })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.05
    if (transparent) this.renderer.setClearColor(0x000000, 0)

    this.scene = new THREE.Scene()

    // 相机：(0, 0.16, 5.2)，视场角 28°
    this.camera = new THREE.PerspectiveCamera(CAMERA_FOV, 1, 0.1, 100)
    this.camera.position.set(CAMERA_POSITION.x, CAMERA_POSITION.y, CAMERA_POSITION.z)
    this.camera.lookAt(0, -0.12, 0)

    // 材质
    this.shellMat = new THREE.MeshStandardMaterial({
      color: ROBOT_COLORS.shell,
      metalness: 0.12, // 陶瓷质感，非金属
      roughness: 0.34,
    })
    this.seamMat = new THREE.MeshStandardMaterial({
      color: COLOR_SEAM,
      metalness: 0.1,
      roughness: 0.45,
    })
    this.glowMat = new THREE.MeshStandardMaterial({
      color: ROBOT_COLORS.glow,
      emissive: ROBOT_COLORS.glow,
      emissiveIntensity: 1.5,
      metalness: 0.2,
      roughness: 0.3,
    })
    this.screenMat = new THREE.MeshStandardMaterial({
      color: ROBOT_COLORS.screen,
      metalness: 0.15,
      roughness: 0.08,
    })
    this.screenInnerMat = new THREE.MeshStandardMaterial({
      color: ROBOT_COLORS.screenInner,
      metalness: 0.1,
      roughness: 0.5,
    })
    this.jointMat = new THREE.MeshStandardMaterial({
      color: ROBOT_COLORS.joint,
      metalness: 0.55,
      roughness: 0.42,
    })

    this.buildLights()
    this.buildHead()
    this.buildNeck()
    this.buildBody()
    this.buildGround()

    this.root.scale.setScalar(ROOT_SCALE)
    this.scene.add(this.root)

    this.resize()
  }

  // ────────────────────────────── 6.4 灯光（5 盏） ──────────────────────────────

  buildLights() {
    // 环境光 #ffffff 0.95
    const ambient = new THREE.AmbientLight(0xffffff, 0.95)
    this.scene.add(ambient)

    // 主光 #ffffff 1.35
    const key = new THREE.DirectionalLight(0xffffff, 1.35)
    key.position.set(3.2, 4.4, 4.2)
    this.scene.add(key)

    // 补光 #dcecff（冷白）0.75
    const fill = new THREE.DirectionalLight(0xdcecff, 0.75)
    fill.position.set(-3.6, 1.8, 3.0)
    this.scene.add(fill)

    // 轮廓光 #6cc4ff（青蓝）0.9
    const rim = new THREE.DirectionalLight(0x6cc4ff, 0.9)
    rim.position.set(-2.2, 1.2, -4.0)
    this.scene.add(rim)

    // 底部反射 #ffffff 0.35
    const bounce = new THREE.DirectionalLight(0xffffff, 0.35)
    bounce.position.set(0, -4.0, 1.4)
    this.scene.add(bounce)
  }

  // ────────────────────────────── 头部组 ──────────────────────────────

  buildHead() {
    this.head.position.y = HEAD_BASE_Y

    // 头盔：横向略宽椭球，半径 0.42，scale(1.06, 0.98, 1.0)
    const helmet = new THREE.Mesh(new THREE.SphereGeometry(0.42, 64, 48), this.shellMat)
    helmet.scale.set(1.06, 0.98, 1.0)
    this.head.add(helmet)

    // 头顶中缝分件
    const seam = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.022, 0.34), this.seamMat)
    seam.position.set(0, 0.4, 0.02)
    this.head.add(seam)
    const seamButton = new THREE.Mesh(new THREE.SphereGeometry(0.032, 24, 16), this.glowMat)
    seamButton.position.set(0, 0.418, -0.16)
    seamButton.scale.set(1, 0.75, 1)
    this.head.add(seamButton)

    // 屏幕内凹底衬：更深的黑
    const inner = new THREE.Mesh(
      new THREE.SphereGeometry(0.376, 64, 48, Math.PI * 0.18, Math.PI * 0.64, Math.PI * 0.2, Math.PI * 0.62),
      this.screenInnerMat,
    )
    inner.scale.set(1.06, 0.98, 1.0)
    this.head.add(inner)

    // 屏幕：球面切片，半径 0.385，近黑玻璃，scale(1.06, 0.98, 1.0)
    const screen = new THREE.Mesh(
      new THREE.SphereGeometry(0.385, 64, 48, Math.PI * 0.2, Math.PI * 0.6, Math.PI * 0.22, Math.PI * 0.56),
      this.screenMat,
    )
    screen.scale.set(1.06, 0.98, 1.0)
    this.head.add(screen)

    // 屏幕边框：半径 0.30 圆环，scale(1.0, 0.84, 0.55)
    const bezel = new THREE.Mesh(new THREE.TorusGeometry(0.3, 0.016, 16, 72), this.seamMat)
    bezel.position.z = 0.303
    bezel.scale.set(1.0, 0.84, 0.55)
    this.head.add(bezel)

    // 眼睛 ×2：胶囊形，z = 0.452，发光蓝
    for (const side of [-1, 1]) {
      const pivot = new THREE.Group()
      pivot.position.set(0.112 * side, 0.062, 0.452)

      const eye = new THREE.Mesh(new THREE.CapsuleGeometry(0.027, 0.055, 8, 20), this.glowMat)
      pivot.add(eye)

      this.eyePivots.push(pivot)
      this.eyes.push(eye)
      this.head.add(pivot)
    }

    // 嘴：上弯弧线（半圆环），半径 0.068，线粗 0.012
    const mouth = new THREE.Mesh(new THREE.TorusGeometry(0.068, 0.012, 10, 40, Math.PI), this.glowMat)
    this.mouthBaseY = -0.088
    mouth.position.set(0, this.mouthBaseY, 0.452)
    mouth.rotation.z = Math.PI // 下半圈 → 微笑上弯
    this.mouth = mouth
    this.head.add(mouth)

    // 耳件 ×2：三层结构 —— 发光块 + 白色盖板 + 外圈
    for (const side of [-1, 1]) {
      const ear = new THREE.Group()
      ear.position.set(0.436 * side, 0.0, 0.03)

      // 1) 发光块
      const glowBlock = new THREE.Mesh(new THREE.CylinderGeometry(0.084, 0.084, 0.05, 28), this.glowMat)
      glowBlock.rotation.z = Math.PI / 2
      ear.add(glowBlock)

      // 2) 白色盖板
      const cap = new THREE.Mesh(new THREE.CylinderGeometry(0.072, 0.072, 0.036, 28), this.shellMat)
      cap.rotation.z = Math.PI / 2
      cap.position.x = 0.036 * side
      ear.add(cap)

      // 3) 外圈
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.088, 0.013, 12, 36), this.shellMat)
      ring.rotation.y = Math.PI / 2
      ear.add(ring)

      this.head.add(ear)
    }

    this.root.add(this.head)
  }

  // ────────────────────────────── 颈部 ──────────────────────────────

  buildNeck() {
    const neck = new THREE.Group()

    // 短柱
    const column = new THREE.Mesh(new THREE.CylinderGeometry(0.115, 0.13, 0.2, 32), this.jointMat)
    column.position.y = -0.19
    neck.add(column)

    // 3 道颈环
    for (let i = 0; i < 3; i += 1) {
      const ring = new THREE.Mesh(new THREE.TorusGeometry(0.128, 0.011, 10, 40), this.shellMat)
      ring.rotation.x = Math.PI / 2
      ring.position.y = -0.13 - i * 0.055
      neck.add(ring)
    }

    this.root.add(neck)
  }

  // ────────────────────────────── 身体组 ──────────────────────────────

  buildBody() {
    this.body.position.y = BODY_BASE_Y

    // 躯干：胶囊体，scale(1.0, 0.95, 0.82)
    const torso = new THREE.Mesh(new THREE.CapsuleGeometry(0.26, 0.28, 16, 40), this.shellMat)
    torso.scale.set(1.0, 0.95, 0.82)
    this.body.add(torso)

    // 躯干下沿分件
    const hipPlate = new THREE.Mesh(new THREE.SphereGeometry(0.235, 40, 28), this.seamMat)
    hipPlate.scale.set(1.0, 0.55, 0.86)
    hipPlate.position.y = -0.3
    this.body.add(hipPlate)

    // 胸条：水平发光条
    const chest = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.032, 0.03), this.glowMat)
    chest.position.set(0, 0.04, 0.209)
    this.body.add(chest)

    const chestDot = new THREE.Mesh(new THREE.SphereGeometry(0.026, 20, 14), this.glowMat)
    chestDot.position.set(0, 0.13, 0.2)
    this.body.add(chestDot)

    // 肩部托板：接住脖子下端，y 局部 0.1575
    const shoulderDeck = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.205, 0.06, 40), this.seamMat)
    shoulderDeck.position.y = 0.1575
    this.body.add(shoulderDeck)

    // 手臂 ×2：由「肩部枢轴 → 上臂 → 肘部枢轴 → 前臂 + 手」两级构成，
    // 这样上臂与肘部可分别旋转，形成挥手/思考等肢体动作。
    for (const side of [-1, 1]) {
      const shoulder = new THREE.Mesh(new THREE.SphereGeometry(0.082, 26, 20), this.shellMat)
      shoulder.position.set(0.268 * side, 0.115, 0)
      this.body.add(shoulder)

      // 上臂枢轴：原点落在肩关节，绕 z 轴旋转即抬臂
      const upperPivot = new THREE.Group()
      upperPivot.position.set(0.288 * side, 0.115, 0)

      const upperArm = new THREE.Mesh(new THREE.CapsuleGeometry(0.06, 0.13, 12, 24), this.shellMat)
      upperArm.position.y = -0.135
      upperPivot.add(upperArm)

      // 臂条：发光
      const armStrip = new THREE.Mesh(new THREE.BoxGeometry(0.016, 0.09, 0.016), this.glowMat)
      armStrip.position.set(0, -0.135, 0.06)
      upperPivot.add(armStrip)

      const elbow = new THREE.Mesh(new THREE.SphereGeometry(0.055, 22, 18), this.jointMat)
      elbow.position.y = -0.275
      upperPivot.add(elbow)

      // 肘部枢轴：原点落在肘关节，绕 z 轴旋转即屈肘
      const forePivot = new THREE.Group()
      forePivot.position.y = -0.275

      const foreArm = new THREE.Mesh(new THREE.CapsuleGeometry(0.052, 0.115, 12, 24), this.shellMat)
      foreArm.position.y = -0.11
      forePivot.add(foreArm)

      // 手：掌 + 手指
      const hand = new THREE.Group()
      hand.position.y = -0.24

      const palm = new THREE.Mesh(new THREE.SphereGeometry(0.062, 24, 18), this.jointMat)
      palm.scale.set(1.0, 0.9, 0.78)
      hand.add(palm)

      for (let f = -1; f <= 1; f += 1) {
        const finger = new THREE.Mesh(new THREE.CapsuleGeometry(0.017, 0.05, 6, 12), this.jointMat)
        finger.position.set(0.032 * f, -0.056, 0.012)
        hand.add(finger)
      }
      forePivot.add(hand)

      upperPivot.add(forePivot)
      this.body.add(upperPivot)

      this.armPivots.push({ side, upper: upperPivot, fore: forePivot })
    }

    // 腿 ×2：短粗腿（Q 版比例），脚 ×2：扁平脚掌
    for (const side of [-1, 1]) {
      const hipJoint = new THREE.Mesh(new THREE.SphereGeometry(0.072, 24, 18), this.jointMat)
      hipJoint.position.set(0.108 * side, -0.315, 0)
      this.body.add(hipJoint)

      const leg = new THREE.Mesh(new THREE.CapsuleGeometry(0.078, 0.13, 14, 26), this.shellMat)
      leg.position.set(0.108 * side, -0.44, 0)
      this.body.add(leg)

      const knee = new THREE.Mesh(new THREE.SphereGeometry(0.06, 22, 16), this.jointMat)
      knee.position.set(0.108 * side, -0.545, 0)
      this.body.add(knee)

      // 扁平脚掌
      const foot = new THREE.Mesh(new THREE.SphereGeometry(0.085, 26, 20), this.shellMat)
      foot.scale.set(0.95, 0.42, 1.5)
      foot.position.set(0.108 * side, -0.625, 0.035)
      this.body.add(foot)

      // 脚环：发光
      const footRing = new THREE.Mesh(new THREE.TorusGeometry(0.082, 0.012, 10, 32), this.glowMat)
      footRing.rotation.x = Math.PI / 2
      footRing.position.set(0.108 * side, -0.645, 0.02)
      footRing.scale.set(0.95, 1.4, 1.5)
      this.body.add(footRing)
    }

    this.root.add(this.body)
  }

  // ────────────────────────────── 地面效果 ──────────────────────────────

  buildGround() {
    // groundShadow：椭圆形投影，随悬浮高度缩放变淡
    const shadowMat = new THREE.MeshBasicMaterial({
      color: ROBOT_COLORS.screenInner,
      transparent: true,
      opacity: SHADOW_OPACITY_NEAR,
      depthWrite: false,
    })
    const shadow = new THREE.Mesh(new THREE.CircleGeometry(0.5, 64), shadowMat)
    shadow.rotation.x = -Math.PI / 2
    shadow.position.y = GROUND_Y
    shadow.scale.set(1.35, 1.0, 1.0)
    this.groundShadow = shadow
    this.shadowMaterial = shadowMat
    this.root.add(shadow)

    // groundRing：旋转发光环，脉动
    const ringMat = new THREE.MeshStandardMaterial({
      color: ROBOT_COLORS.glow,
      emissive: ROBOT_COLORS.glow,
      emissiveIntensity: RING_EMISSIVE_BASE,
      metalness: 0.3,
      roughness: 0.3,
      transparent: true,
      opacity: 0.85,
    })
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.58, 0.012, 12, 96), ringMat)
    ring.rotation.x = -Math.PI / 2
    ring.position.y = GROUND_Y + 0.006
    this.groundRing = ring
    this.ringMaterial = ringMat
    this.root.add(ring)
  }

  // ────────────────────────────── 对外接口 ──────────────────────────────

  /** 开始渲染循环 */
  start() {
    if (this.running || this.disposed) return
    this.running = true
    this.clock.start()
    const tick = () => {
      if (!this.running) return
      this.rafId = requestAnimationFrame(tick)
      this.updateAnimations(this.clock.getElapsedTime())
      this.renderer.render(this.scene, this.camera)
    }
    this.rafId = requestAnimationFrame(tick)
  }

  /** 停止渲染循环 */
  stop() {
    this.running = false
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
  }

  /** 开始说话动画（嘴动 + 前倾） */
  speak() {
    this.setSpeaking(true)
  }

  /** 停止说话动画（嘴平滑闭合） */
  stopSpeaking() {
    this.setSpeaking(false)
  }

  setSpeaking(v) {
    this.speakingTarget = v ? 1 : 0
    // 说话时切到讲解手势，停止后若没有一次性动作则回到待机
    if (v) {
      this.setGesture('talking')
    } else if (this.gesture === 'talking') {
      this.setGesture('idle')
    }
  }

  /** ─────────── 肢体动作对外接口 ─────────── */

  /**
   * 切换持续性动作：idle（待机）/ thinking（思考）/ talking（说话）。
   * 一次性动作（wave / nod）请用 playGesture()。
   */
  setGesture(gesture) {
    if (gesture === 'wave' || gesture === 'nod') {
      this.playGesture(gesture)
      return
    }
    this.gesture = gesture
  }

  /** 播放一次性动作：挥手致意 / 点头应答 */
  playGesture(gesture) {
    this.oneshotKind = gesture
    this.oneshotRemain = ONESHOT_DURATION[gesture]
    if (gesture === 'nod') this.nodPhase = 0
  }

  /** 当前动作 */
  getGesture() {
    return this.oneshotKind ?? this.gesture
  }

  /** 容器尺寸变化时调用 */
  resize() {
    const width = this.canvas.clientWidth || 1
    const height = this.canvas.clientHeight || 1
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
    this.renderer.setSize(width, height, false)
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()
  }

  /** 清理（释放几何体与材质） */
  dispose() {
    if (this.disposed) return
    this.stop()
    this.disposed = true

    this.scene.traverse((obj) => {
      const mesh = obj
      if (mesh.geometry) mesh.geometry.dispose()
    })

    for (const mat of [
      this.shellMat,
      this.seamMat,
      this.glowMat,
      this.screenMat,
      this.screenInnerMat,
      this.jointMat,
      this.shadowMaterial,
      this.ringMaterial,
    ]) {
      mat?.dispose()
    }

    this.renderer.dispose()
  }

  // ────────────────────────────── 动画 ──────────────────────────────

  updateAnimations(t) {
    const dt = Math.min(this.clock.getDelta(), 0.05)

    // 说话权重平滑趋近
    this.speakingAmount = damp(this.speakingAmount, this.speakingTarget, 7, dt)

    // 身体浮动：sin(t × 1.1) × 0.035
    const float = Math.sin(t * FLOAT_FREQ) * FLOAT_AMP
    this.root.position.y = float

    // 头部跟随：同相位，幅度 ×1.35
    this.head.position.y = HEAD_BASE_Y + float * HEAD_FOLLOW_FACTOR

    // 左右摇摆：sin(t × 0.7) × 0.016
    this.root.rotation.z = Math.sin(t * SWAY_FREQ) * SWAY_AMP

    // 说话前倾：rotation.x → -0.055
    this.root.rotation.x = damp(this.root.rotation.x, LEAN_MAX * this.speakingAmount, 6, dt)

    this.updateBlink(dt)
    this.updateMouth(t)
    this.updateArms(dt, t)
    this.updateGround(t)
  }

  /**
   * 肢体动作驱动：
   * - idle      双臂自然下垂，随呼吸轻微起伏
   * - thinking  右手抬到脸侧，缓慢小幅摆动（思考状）
   * - talking   双臂抬起做讲解手势，随说话节奏起伏
   * - wave      单臂高举左右摆动（一次性）
   * - nod       头部俯仰两次（一次性）
   */
  updateArms(dt, t) {
    // 一次性动作倒计时
    let waveAmount = 0
    let nodAmount = 0

    if (this.oneshotKind) {
      this.oneshotRemain -= dt
      if (this.oneshotRemain <= 0) {
        this.oneshotKind = null
        this.oneshotRemain = 0
      } else if (this.oneshotKind === 'wave') {
        // 进入与退出各留 0.25s 做平滑，中间保持全幅
        const total = ONESHOT_DURATION.wave
        const elapsed = total - this.oneshotRemain
        waveAmount = Math.min(1, elapsed / 0.25, this.oneshotRemain / 0.25)
      } else {
        const total = ONESHOT_DURATION.nod
        const elapsed = total - this.oneshotRemain
        nodAmount = Math.min(1, elapsed / 0.2, this.oneshotRemain / 0.2)
        this.nodPhase += dt
      }
    }

    // 一次性动作用 0..1 的幅度，覆盖持续性动作
    for (const arm of this.armPivots) {
      // 右手（side = 1）承担挥手与思考手势
      const isActionArm = arm.side === 1

      let targetUpper
      let targetFore
      if (waveAmount > 0 && isActionArm) {
        // 挥手：抬到约 150°，肘部微屈，前臂左右摆
        targetUpper = -2.5
        targetFore = -0.35 + Math.sin(t * 11) * 0.45
      } else if (this.gesture === 'thinking' && isActionArm) {
        targetUpper = ARM_POSE.thinking.upper
        targetFore = ARM_POSE.thinking.fore + Math.sin(t * 1.6) * 0.06
      } else if (this.gesture === 'talking') {
        // 讲解手势：说话权重越大抬得越高，双臂交替起伏
        const phase = arm.side === 1 ? 0 : Math.PI
        const lift = this.speakingAmount * (0.7 + 0.3 * Math.sin(t * 3.4 + phase))
        targetUpper = ARM_POSE.idle.upper + (ARM_POSE.talking.upper - ARM_POSE.idle.upper) * lift
        targetFore = ARM_POSE.idle.fore + (ARM_POSE.talking.fore - ARM_POSE.idle.fore) * lift
      } else {
        // 待机：轻微外张 + 呼吸起伏
        targetUpper = ARM_POSE.idle.upper + Math.sin(t * FLOAT_FREQ) * 0.035
        targetFore = ARM_POSE.idle.fore + Math.sin(t * FLOAT_FREQ + 0.5) * 0.03
      }

      // 左右镜像：绕 z 轴旋转方向相反
      const mirror = arm.side
      arm.upper.rotation.z = damp(
        arm.upper.rotation.z,
        targetUpper * mirror,
        9,
        dt,
      )
      arm.fore.rotation.z = damp(
        arm.fore.rotation.z,
        targetFore * mirror,
        9,
        dt,
      )
      // 挥手时让手臂略微向前，避免与身体穿插
      arm.upper.rotation.x = damp(
        arm.upper.rotation.x,
        waveAmount > 0 && isActionArm ? -0.25 : 0,
        8,
        dt,
      )
    }

    // 点头：叠加到头部 rotation.x（一次性）
    if (nodAmount > 0) {
      const dip = Math.sin(this.nodPhase * 7.2) * 0.14
      this.head.rotation.x = dip * nodAmount
    } else if (this.gesture === 'thinking') {
      // 思考时头部微微歪向一侧
      this.head.rotation.z = damp(this.head.rotation.z, 0.12, 4, dt)
      this.head.rotation.x = damp(this.head.rotation.x, 0, 6, dt)
    } else {
      this.head.rotation.z = damp(this.head.rotation.z, 0, 5, dt)
      this.head.rotation.x = damp(this.head.rotation.x, 0, 6, dt)
    }
  }

  /** 眨眼：间隔 2.6 + random × 3.8 秒，持续 0.11s */
  updateBlink(dt) {
    if (this.blinking) {
      this.blinkProgress += dt / BLINK_DURATION
      if (this.blinkProgress >= 1) {
        this.blinking = false
        this.blinkProgress = 0
        this.blinkCountdown = BLINK_MIN_INTERVAL + Math.random() * BLINK_INTERVAL_RANGE
      }
    } else {
      this.blinkCountdown -= dt
      if (this.blinkCountdown <= 0) {
        this.blinking = true
        this.blinkProgress = 0
      }
    }

    const progress = this.blinking ? Math.min(this.blinkProgress, 1) : 0
    // 压扁再展开：scale.y 最小保留 0.08
    const squash = 1 - Math.sin(Math.PI * progress) * (1 - EYE_MIN_SCALE)
    const scaleY = Math.max(squash, EYE_MIN_SCALE)

    for (const pivot of this.eyePivots) {
      pivot.scale.y = scaleY
    }
  }

  /** 嘴部开合：双频叠加 sin，避免机械感 */
  updateMouth(t) {
    if (!this.mouth) return
    const amount = this.speakingAmount

    // 双频叠加
    const wave =
      0.55 * (0.5 + 0.5 * Math.sin(t * 13.4)) + 0.45 * (0.5 + 0.5 * Math.sin(t * 7.1 + 1.7))

    const open = wave * amount
    this.mouth.scale.set(1 + open * 0.12, 1 + open * 1.15, 1)
    this.mouth.position.y = this.mouthBaseY - open * 0.012
    this.mouth.rotation.z = Math.PI

    // 说话时眼睛轻微放大，增强互动感
    const eyeBoost = 1 + amount * 0.06
    for (const eye of this.eyes) {
      eye.scale.x = eyeBoost
      eye.scale.z = eyeBoost
    }

    // 发光强度随说话波动
    this.glowMat.emissiveIntensity = 1.5 + amount * 0.5 * (0.5 + 0.5 * Math.sin(t * 9))
  }

  /** 投影联动 + 光环脉动 */
  updateGround(t) {
    // 浮越高 → 越大越淡（opacity 0.34→0.18）
    const h = (this.root.position.y / FLOAT_AMP + 1) / 2 // 归一化到 0..1
    const k = THREE.MathUtils.clamp(h, 0, 1)

    if (this.groundShadow && this.shadowMaterial) {
      const s = THREE.MathUtils.lerp(SHADOW_SCALE_NEAR, SHADOW_SCALE_FAR, k)
      this.groundShadow.scale.set(1.35 * s, 1.0 * s, 1.0)
      this.shadowMaterial.opacity = THREE.MathUtils.lerp(
        SHADOW_OPACITY_NEAR,
        SHADOW_OPACITY_FAR,
        k,
      )
    }

    // 光环：emissiveIntensity = 1.2 + sin(t × 1.1) × 0.5，旋转 t × 0.25
    if (this.ringMaterial && this.groundRing) {
      this.ringMaterial.emissiveIntensity =
        RING_EMISSIVE_BASE + Math.sin(t * FLOAT_FREQ) * RING_EMISSIVE_AMP
      this.groundRing.rotation.z = t * RING_SPIN_SPEED
    }
  }
}
