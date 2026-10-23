/**
 * 全景大坝 3D 场景（three.js）
 *
 * 两种坝体来源：
 *  1) 程序化（默认）：零资源、首屏 0 字节，适合演示与离线内网；
 *  2) Blender 小模型（.glb）：调用 loadExternalModel(url) 后自动接管，
 *     按命名约定绑定闸门、机位、水面，程序化坝体整体隐藏。
 *
 * ── Blender 导出命名约定（详见 docs/07-Blender到three.js-小模型流程.md）──
 *   Gate_01 … Gate_06        闸门扇体（原点在门体中心，+Z 在 Blender 里向上 → three 里 +Y）
 *   Water_Surface            水面占位（加载后被水光着色器替换，只取其 XZ 范围）
 *   CamPoint_01 … CamPoint_06 机位空物体；其子物体 CamTarget_0X 为空物体，表示观察点
 *   （机位可选 extras.fov 覆盖视场角）
 *   其余对象（坝体/闸墩/消力池/坝肩…）原样保留。
 *
 * 对外契约：
 *   const scene = createDamScene({ container, onFrame })
 *   scene.setData({ level, thresholds, gates, alarm })
 *   scene.focusPoint('cam-03') / scene.overview() / scene.setAutoTour(true)
 *   scene.setMotion(false) / scene.setQuality('high') / scene.resize() / scene.dispose()
 *   await scene.loadExternalModel('/models/dam.glb')
 */

import * as THREE from 'three'
import { createWaterMaterial } from './waterMaterial.js'
import { CAMERA_POINTS, OVERVIEW_POSE } from './cameraPoints.js'
import {
  clamp,
  damp,
  lerp,
  levelToY,
  poseFromLookAt,
  positionFromPose,
  blendPose,
  smoothstep,
} from './sceneMath.js'

/** 场景尺度（米），也是 Blender 模型的归一化目标长度 */
const DIM = {
  damLength: 120,
  crestY: 26,
  crestWidth: 6,
  baseWidth: 18,
  gateCount: 6,
  gateLift: 6.2,
  gateWidth: 8.6,
  pierWidth: 1.5,
}

const FLY_DURATION = 1.15
const TOUR_INTERVAL = 7.5
const WATER_BASE_SIZE = 300

export function createDamScene({ container, onFrame, quality = 'auto', showCameraPoints = true, showLabels = true, onLabelClick = null } = {}) {
  const host = container
  if (!host) throw new Error('createDamScene: 需要 container')

  const canvas = document.createElement('canvas')
  canvas.className = 'dam-scene__canvas'
  canvas.setAttribute('aria-hidden', 'true')
  host.appendChild(canvas)

  const reducedQuery = typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia('(prefers-reduced-motion: reduce)')
    : null

  const isSmall = () => host.clientWidth < 720
  const highQuality = quality === 'high' || (quality === 'auto' && !isSmall())

  let renderer
  try {
    renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: highQuality,
      alpha: true,
      powerPreference: 'high-performance',
    })
  } catch (err) {
    host.removeChild(canvas)
    throw new Error(`WEBGL_UNAVAILABLE: ${err?.message || err}`)
  }

  renderer.setClearColor(0x000000, 0)
  renderer.outputColorSpace = THREE.SRGBColorSpace
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  renderer.toneMappingExposure = 1.22
  renderer.shadowMap.enabled = highQuality
  renderer.shadowMap.type = THREE.PCFSoftShadowMap

  const scene = new THREE.Scene()
  scene.fog = new THREE.FogExp2(0x0b2e38, 0.0042)

  const camera = new THREE.PerspectiveCamera(46, 1, 0.5, 1200)

  /**
   * 机位表：从 cameraPoints.js 拷贝一份可变副本。
   * 模型里的 CamPoint_XX 若存在，会用模型坐标覆盖 position/target。
   */
  const cameras = CAMERA_POINTS.map((point) => ({
    ...point,
    position: [...point.position],
    target: [...point.target],
  }))

  const state = {
    level: null,
    thresholds: { die: null, design: null, flood: null },
    gateTargets: Array(DIM.gateCount).fill(0),
    alarm: 0,
    motion: !(reducedQuery && reducedQuery.matches),
    autoTour: false,
    activePoint: null,
    waterY: 16,
    waterBaseY: null,
    waterSurfaces: 0,
    waterRise: 0,
    alarmRingScale: 1,
    foam: 0.3,
    damX: 0,
    tourTimer: TOUR_INTERVAL,
    fps: 0,
    modelSource: 'procedural',
  }

  // ───────────────────────── 灯光 ─────────────────────────
  const hemi = new THREE.HemisphereLight(0x9fd8ee, 0x183038, 1.2)
  scene.add(hemi)

  const sun = new THREE.DirectionalLight(0xfff2d8, 2.8)
  sun.position.set(-70, 96, 52)
  sun.castShadow = highQuality
  if (highQuality) {
    sun.shadow.mapSize.set(1024, 1024)
    sun.shadow.camera.near = 20
    sun.shadow.camera.far = 320
    sun.shadow.camera.left = -130
    sun.shadow.camera.right = 130
    sun.shadow.camera.top = 130
    sun.shadow.camera.bottom = -130
    sun.shadow.bias = -0.0004
    // 沙盘这类薄壁大平面很容易出现斜向"阴影条纹"(acne)，用 normalBias 压掉
    sun.shadow.normalBias = 0.9
  }
  scene.add(sun)
  scene.add(sun.target)

  const fill = new THREE.DirectionalLight(0x8fd0ff, 0.45)
  fill.position.set(80, 40, -70)
  scene.add(fill)

  // ───────────────────────── 材质 ─────────────────────────
  const matConcrete = new THREE.MeshStandardMaterial({
    color: 0xb8c6cc,
    roughness: 0.88,
    metalness: 0.04,
  })
  const matConcreteDark = new THREE.MeshStandardMaterial({
    color: 0x8b9aa1,
    roughness: 0.92,
    metalness: 0.03,
  })
  const matSteel = new THREE.MeshStandardMaterial({
    color: 0x7f8f98,
    roughness: 0.42,
    metalness: 0.72,
  })
  const matRock = new THREE.MeshStandardMaterial({
    color: 0x3f4f45,
    roughness: 1,
    metalness: 0,
    flatShading: true,
  })
  const matBed = new THREE.MeshStandardMaterial({ color: 0x0a2028, roughness: 1 })

  // ───────────────────────── 地形（一张网格做出河谷） ─────────────────────────
  const terrainGroup = new THREE.Group()
  terrainGroup.name = 'terrain'

  /**
   * 河谷高度场：河道沿 X 方向（水从上游 -X 流向下游 +X），坝轴沿 Z。
   * |z| < 46 是河床（低于水面），46→130 抬升成岸坡，再往外继续抬高成山体。
   * 这样水面四周被岸坡自然收口，不会出现"悬空的方形水片"。
   */
  function valleyHeight(x, z) {
    const az = Math.abs(z)
    let base = -7 + Math.sin(x * 0.045) * 0.9 + Math.cos(z * 0.06) * 0.7
    if (x > 20) base = lerp(base, 2.4 + Math.sin(z * 0.05) * 1.2, smoothstep(20, 90, x))
    const bank = smoothstep(46, 132, az)
    const ridge = 19 + Math.sin(x * 0.028 + z * 0.021) * 4.5 + Math.cos(x * 0.07) * 1.6
    let h = lerp(base, ridge, bank)
    h += smoothstep(150, 330, az) * 16
    // 上游库尾也稍微收高，形成库区回水
    if (x < -200) h += smoothstep(-200, -330, x) * 10
    return h
  }

  const terrainGeo = new THREE.PlaneGeometry(900, 900, 110, 110)
  terrainGeo.rotateX(-Math.PI / 2)
  const terrainPos = terrainGeo.attributes.position
  for (let i = 0; i < terrainPos.count; i += 1) {
    terrainPos.setY(i, valleyHeight(terrainPos.getX(i), terrainPos.getZ(i)))
  }
  terrainGeo.computeVertexNormals()

  const terrain = new THREE.Mesh(terrainGeo, matRock)
  terrain.receiveShadow = true
  terrainGroup.add(terrain)
  scene.add(terrainGroup)

  // ───────────────────────── 水面（水光流动） ─────────────────────────
  const { material: waterMaterial, uniforms: waterUniforms } = createWaterMaterial(THREE, {
    segments: highQuality ? { x: 150, y: 110 } : { x: 80, y: 60 },
  })
  const waterGeometry = new THREE.PlaneGeometry(WATER_BASE_SIZE, WATER_BASE_SIZE, 150, 110)
  const water = new THREE.Mesh(waterGeometry, waterMaterial)
  water.rotation.x = -Math.PI / 2
  water.position.set(-148, 16, 0)
  water.name = 'water-shader'
  scene.add(water)

  // ───────────────────────── 程序化坝体 ─────────────────────────
  const damGroup = new THREE.Group()
  damGroup.name = 'procedural-dam'

  const profile = new THREE.Shape()
  profile.moveTo(0, 0)
  profile.lineTo(0, DIM.crestY)
  profile.lineTo(DIM.crestWidth, DIM.crestY)
  profile.lineTo(DIM.baseWidth, 0)
  profile.lineTo(0, 0)

  const bodyGeo = new THREE.ExtrudeGeometry(profile, {
    depth: DIM.damLength,
    bevelEnabled: false,
    curveSegments: 1,
  })
  bodyGeo.translate(0, 0, -DIM.damLength / 2)
  bodyGeo.computeVertexNormals()
  const body = new THREE.Mesh(bodyGeo, matConcrete)
  body.castShadow = highQuality
  body.receiveShadow = true
  damGroup.add(body)

  const road = new THREE.Mesh(new THREE.BoxGeometry(DIM.crestWidth, 0.35, DIM.damLength), matConcreteDark)
  road.position.set(DIM.crestWidth / 2, DIM.crestY + 0.18, 0)
  road.receiveShadow = true
  damGroup.add(road)

  const parapet = new THREE.Mesh(new THREE.BoxGeometry(0.5, 1.15, DIM.damLength), matConcrete)
  parapet.position.set(-0.25, DIM.crestY + 0.85, 0)
  parapet.castShadow = highQuality
  damGroup.add(parapet)

  const chute = new THREE.Mesh(new THREE.BoxGeometry(26, 0.9, 62), matConcreteDark)
  chute.position.set(9.5, 12.4, 0)
  chute.rotation.z = -0.31
  chute.receiveShadow = true
  damGroup.add(chute)

  const basin = new THREE.Mesh(new THREE.BoxGeometry(46, 1.2, 74), matBed)
  basin.position.set(34, 0.9, 0)
  basin.receiveShadow = true
  damGroup.add(basin)

  const basinWall = new THREE.Mesh(new THREE.BoxGeometry(1.6, 4.2, 74), matConcreteDark)
  basinWall.position.set(56, 2.2, 0)
  damGroup.add(basinWall)

  for (const sign of [1, -1]) {
    const abutment = new THREE.Mesh(new THREE.BoxGeometry(22, 30, 12), matConcrete)
    abutment.position.set(6, 15, sign * (DIM.damLength / 2 + 5))
    abutment.castShadow = highQuality
    abutment.receiveShadow = true
    damGroup.add(abutment)
  }

  // 闸门 + 闸墩 + 门机
  const gateSpan = DIM.gateWidth + DIM.pierWidth
  const gateStartZ = -((DIM.gateCount - 1) * gateSpan) / 2
  const indicatorGroup = new THREE.Group()
  /** @type {THREE.Mesh[]} 程序化闸门，加载模型后会被替换 */
  let gateMeshes = []

  for (let i = 0; i < DIM.gateCount; i += 1) {
    const z = gateStartZ + i * gateSpan

    const gate = new THREE.Mesh(new THREE.BoxGeometry(0.9, 6.6, DIM.gateWidth), matSteel.clone())
    gate.position.set(0.55, 21.4, z)
    gate.castShadow = highQuality
    gate.userData = { baseY: gate.position.y, index: i, procedural: true }
    damGroup.add(gate)
    gateMeshes.push(gate)

    const pier = new THREE.Mesh(new THREE.BoxGeometry(14, 8.4, DIM.pierWidth), matConcrete)
    pier.position.set(6.4, 22, z + gateSpan / 2)
    pier.castShadow = highQuality
    pier.receiveShadow = true
    damGroup.add(pier)

    const gantry = new THREE.Mesh(new THREE.BoxGeometry(3.2, 0.7, DIM.gateWidth), matSteel)
    gantry.position.set(1.5, DIM.crestY + 2.6, z)
    damGroup.add(gantry)

    const lamp = new THREE.Mesh(
      new THREE.SphereGeometry(0.42, 10, 10),
      new THREE.MeshBasicMaterial({ color: 0x2f6f52 }),
    )
    lamp.position.set(-0.15, DIM.crestY + 1.9, z)
    indicatorGroup.add(lamp)
  }
  damGroup.add(indicatorGroup)
  scene.add(damGroup)

  // ───────────────────────── 告警光环 ─────────────────────────
  const alarmRing = new THREE.Mesh(
    new THREE.RingGeometry(26, 29, 64),
    new THREE.MeshBasicMaterial({
      color: 0xff3b30,
      transparent: true,
      opacity: 0,
      side: THREE.DoubleSide,
      depthWrite: false,
    }),
  )
  alarmRing.rotation.x = -Math.PI / 2
  alarmRing.position.set(2, DIM.crestY + 0.6, 0)
  alarmRing.visible = false
  scene.add(alarmRing)

  // ───────────────────────── 机位光点 ─────────────────────────
  const waterSurfaces = []
  const pointMeshes = new Map()
  const pointGeo = new THREE.SphereGeometry(0.85, 12, 12)
  const ringGeo = new THREE.RingGeometry(1.6, 2.1, 24)

  function syncPointMeshes() {
    for (const cam of cameras) {
      const group = pointMeshes.get(cam.id)
      if (!group) continue
      group.position.set(cam.position[0], cam.position[1], cam.position[2])
    }
  }

  if (showCameraPoints) {
    for (const cam of cameras) {
      const group = new THREE.Group()
      group.position.set(cam.position[0], cam.position[1], cam.position[2])

      const dot = new THREE.Mesh(
        pointGeo,
        new THREE.MeshBasicMaterial({ color: 0x4fd1ff, transparent: true, opacity: 0.95 }),
      )
      group.add(dot)

      const ring = new THREE.Mesh(
        ringGeo,
        new THREE.MeshBasicMaterial({
          color: 0x4fd1ff,
          transparent: true,
          opacity: 0.5,
          side: THREE.DoubleSide,
          depthWrite: false,
        }),
      )
      group.add(ring)
      group.userData = { id: cam.id, dot, ring }
      pointMeshes.set(cam.id, group)
      scene.add(group)
    }
  }

  // ───────────────────────── 三维标签（Sprite） ─────────────────────────
  const LABEL_ANCHORS = {
    drowning: [-34, 1.6, 5],
    boat: [-6, 1.6, -22],
  }
  const labelSprites = []
  const labelRaycaster = new THREE.Raycaster()

  function labelColor(tone) {
    if (tone === 'normal') return '#2ee0a4'
    if (tone === 'warning') return '#f2c14e'
    if (tone === 'error') return '#ff5d55'
    return '#8fa3b3'
  }

  function drawLabelIcon(ctx, key, cx, cy) {
    ctx.save()
    ctx.translate(cx, cy)
    ctx.fillStyle = '#7fe0ff'
    if (key === 'drowning') {
      ctx.beginPath()
      ctx.moveTo(0, -32)
      ctx.bezierCurveTo(22, -6, 25, 13, 0, 30)
      ctx.bezierCurveTo(-25, 13, -22, -6, 0, -32)
      ctx.fill()
      ctx.fillStyle = 'rgba(4, 24, 35, .55)'
      ctx.beginPath()
      ctx.arc(0, 12, 7, 0, Math.PI * 2)
      ctx.fill()
    } else {
      ctx.beginPath()
      ctx.moveTo(-34, 12)
      ctx.lineTo(34, 12)
      ctx.lineTo(20, 30)
      ctx.lineTo(-20, 30)
      ctx.closePath()
      ctx.fill()
      ctx.fillRect(-15, -10, 30, 18)
      ctx.fillStyle = 'rgba(4, 24, 35, .55)'
      ctx.fillRect(-9, -5, 8, 8)
      ctx.fillRect(2, -5, 8, 8)
    }
    ctx.restore()
  }

  function drawLabelTexture(name, status, tone) {
    const canvas = document.createElement('canvas')
    canvas.width = 1024
    canvas.height = 360
    const ctx = canvas.getContext('2d')
    ctx.clearRect(0, 0, canvas.width, canvas.height)

    ctx.beginPath()
    ctx.roundRect(6, 6, 1012, 348, 42)
    ctx.fillStyle = 'rgba(4, 24, 35, .86)'
    ctx.fill()
    ctx.lineWidth = 3
    ctx.strokeStyle = 'rgba(126, 214, 244, .38)'
    ctx.stroke()

    ctx.beginPath()
    ctx.arc(100, 180, 58, 0, Math.PI * 2)
    ctx.fillStyle = 'rgba(79, 209, 255, .16)'
    ctx.fill()
    ctx.strokeStyle = 'rgba(79, 209, 255, .45)'
    ctx.lineWidth = 2
    ctx.stroke()
    drawLabelIcon(ctx, name === '无人艇' ? 'boat' : 'drowning', 100, 180)

    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#e9fbff'
    ctx.font = '600 76px "Microsoft YaHei", "PingFang SC", sans-serif'
    ctx.fillText(name, 190, 138)
    ctx.fillStyle = '#9dbccb'
    ctx.font = '400 42px "Microsoft YaHei", "PingFang SC", sans-serif'
    ctx.fillText(status, 192, 224)

    const color = labelColor(tone)
    ctx.beginPath()
    ctx.arc(940, 180, 19, 0, Math.PI * 2)
    ctx.fillStyle = color
    ctx.shadowColor = color
    ctx.shadowBlur = 22
    ctx.fill()
    ctx.shadowBlur = 0

    const texture = new THREE.CanvasTexture(canvas)
    texture.colorSpace = THREE.SRGBColorSpace
    texture.minFilter = THREE.LinearFilter
    texture.magFilter = THREE.LinearFilter
    texture.anisotropy = 4
    return texture
  }

  function addLabelSprite(key, name) {
    const anchor = LABEL_ANCHORS[key]
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
      map: drawLabelTexture(name, '未知', 'unknown'),
      transparent: true,
      depthWrite: false,
      depthTest: false,
    }))
    sprite.scale.set(26, 9.14, 1)
    sprite.center.set(0.5, 0)
    sprite.position.set(anchor[0], anchor[1] + 2.6, anchor[2])
    sprite.renderOrder = 30
    sprite.userData.key = key
    scene.add(sprite)

    const lineGeometry = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(anchor[0], anchor[1], anchor[2]),
      new THREE.Vector3(anchor[0], anchor[1] + 2.6, anchor[2]),
    ])
    const line = new THREE.Line(lineGeometry, new THREE.LineBasicMaterial({
      color: 0x4fd1ff,
      transparent: true,
      opacity: 0.45,
    }))
    scene.add(line)

    const dot = new THREE.Mesh(
      new THREE.SphereGeometry(0.38, 10, 10),
      new THREE.MeshBasicMaterial({ color: 0x4fd1ff, transparent: true, opacity: 0.9 }),
    )
    dot.position.set(anchor[0], anchor[1], anchor[2])
    scene.add(dot)

    labelSprites.push({ key, name, sprite, line, dot, signature: '' })
  }

  function setLabelState(key, state) {
    const item = labelSprites.find((entry) => entry.key === key)
    if (!item) return
    const name = state?.name || item.name
    const status = state?.status || '未知'
    const tone = state?.tone || 'unknown'
    const signature = `${name}|${status}|${tone}`
    if (item.signature === signature) return
    item.signature = signature
    const texture = drawLabelTexture(name, status, tone)
    const previous = item.sprite.material.map
    item.sprite.material.map = texture
    item.sprite.material.needsUpdate = true
    previous?.dispose()
    item.dot.material.color.set(labelColor(tone))
    item.line.material.color.set(labelColor(tone))
  }

  if (showLabels) {
    addLabelSprite('drowning', '溺水监测点')
    addLabelSprite('boat', '无人艇')
  }

  // ───────────────────────── 相机控制 ─────────────────────────
  const overviewPose = poseFromLookAt(OVERVIEW_POSE.position, OVERVIEW_POSE.target)
  const pose = { ...overviewPose, target: [...overviewPose.target] }
  let goal = { ...overviewPose, target: [...overviewPose.target] }
  let fly = null
  let fovNow = OVERVIEW_POSE.fov
  let fovGoal = OVERVIEW_POSE.fov

  function applyCamera() {
    const [x, y, z] = positionFromPose(pose)
    camera.position.set(x, y, z)
    camera.fov = fovNow
    camera.lookAt(pose.target[0], pose.target[1], pose.target[2])
    camera.updateProjectionMatrix()
  }

  function startFly(next, fov = OVERVIEW_POSE.fov) {
    fly = {
      from: { ...pose, target: [...pose.target] },
      to: { ...next, target: [...next.target] },
      fovFrom: fovNow,
      fovTo: fov,
      t: 0,
    }
    state.autoTour = false
  }

  // ───────────────────────── 交互 ─────────────────────────
  let dragging = false
  let lastX = 0
  let lastY = 0
  let startX = 0
  let startY = 0
  let moved = false
  let pointerId = null

  function onPointerDown(event) {
    if (event.button !== 0 && event.pointerType === 'mouse') return
    dragging = true
    fly = null
    lastX = event.clientX
    lastY = event.clientY
    startX = event.clientX
    startY = event.clientY
    moved = false
    pointerId = event.pointerId
    canvas.setPointerCapture?.(event.pointerId)
    canvas.style.cursor = 'grabbing'
  }

  function onPointerMove(event) {
    if (!dragging) return
    const dx = event.clientX - lastX
    const dy = event.clientY - lastY
    lastX = event.clientX
    lastY = event.clientY
    if (Math.hypot(event.clientX - startX, event.clientY - startY) > 4) {
      moved = true
    }
    pose.azimuth -= dx * 0.0045
    pose.polar = clamp(pose.polar - dy * 0.004, 0.16, 1.46)
    goal = { ...pose, target: [...pose.target] }
  }

  function onPointerUp(event) {
    const shouldClick = !moved && event?.type === 'pointerup'
    dragging = false
    pointerId = null
    canvas.style.cursor = 'grab'
    if (!shouldClick || labelSprites.length === 0 || typeof onLabelClick !== 'function') return
    const rect = canvas.getBoundingClientRect()
    if (!rect.width || !rect.height) return
    const ndc = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    )
    labelRaycaster.setFromCamera(ndc, camera)
    const hits = labelRaycaster.intersectObjects(labelSprites.map((entry) => entry.sprite), false)
    if (hits.length > 0) {
      onLabelClick(hits[0].object.userData.key)
    }
  }

  function onWheel(event) {
    event.preventDefault()
    fly = null
    pose.distance = clamp(pose.distance * Math.exp(event.deltaY * 0.0011), 26, 300)
    goal = { ...pose, target: [...pose.target] }
  }

  canvas.style.cursor = 'grab'
  canvas.style.touchAction = 'none'
  canvas.addEventListener('pointerdown', onPointerDown)
  canvas.addEventListener('pointermove', onPointerMove)
  canvas.addEventListener('pointerup', onPointerUp)
  canvas.addEventListener('pointercancel', onPointerUp)
  canvas.addEventListener('pointerleave', onPointerUp)
  canvas.addEventListener('wheel', onWheel, { passive: false })

  // ───────────────────────── 尺寸 ─────────────────────────
  function resize() {
    const width = Math.max(1, host.clientWidth)
    const height = Math.max(1, host.clientHeight)
    const ratio = Math.min(window.devicePixelRatio || 1, highQuality ? 1.75 : 1.25)
    renderer.setPixelRatio(ratio)
    renderer.setSize(width, height, false)
    camera.aspect = width / height
    camera.updateProjectionMatrix()
  }

  const resizeObserver = typeof ResizeObserver !== 'undefined'
    ? new ResizeObserver(() => resize())
    : null
  resizeObserver?.observe(host)
  resize()

  // ───────────────────────── 数据接口 ─────────────────────────
  const gateCurrent = new Array(DIM.gateCount).fill(0)

  function setData(next = {}) {
    if ('level' in next) state.level = next.level
    if ('thresholds' in next && next.thresholds) {
      state.thresholds = { ...state.thresholds, ...next.thresholds }
    }
    if ('gates' in next && Array.isArray(next.gates)) {
      for (let i = 0; i < DIM.gateCount; i += 1) {
        const raw = next.gates[i]
        state.gateTargets[i] = raw === 1 || raw === '1' || raw === true ? 1 : 0
      }
    }
    if ('alarm' in next) state.alarm = clamp(Number(next.alarm) || 0, 0, 1)
  }

  function focusPoint(id) {
    const cam = cameras.find((item) => item.id === id)
    if (!cam) return false
    startFly(poseFromLookAt(cam.position, cam.target), cam.fov)
    state.activePoint = id
    return true
  }

  function overview() {
    startFly({ ...overviewPose, target: [...overviewPose.target] }, OVERVIEW_POSE.fov)
    state.activePoint = null
  }

  function setAutoTour(enabled) {
    state.autoTour = Boolean(enabled)
    state.tourTimer = 0
    if (!state.autoTour) state.activePoint = null
  }

  function setMotion(enabled) {
    state.motion = Boolean(enabled)
  }

  function setQuality(level) {
    const next = level === 'high'
    renderer.shadowMap.enabled = next
    sun.castShadow = next
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, next ? 1.75 : 1.25))
    resize()
  }

  // ───────────────────────── 外部小模型（Blender → glb） ─────────────────────────
  const tmpBox = new THREE.Box3()
  const tmpSize = new THREE.Vector3()
  const tmpCenter = new THREE.Vector3()

  /**
   * 只统计网格的包围盒，并跳过指定名字的子树。
   * 水面占位（Water_Surface）是 300 m 见方，若计入会把整坝缩放算错。
   */
  function meshBounds(root, excludeNames = new Set()) {
    const box = new THREE.Box3()
    const one = new THREE.Box3()
    root.updateWorldMatrix(true, true)
    root.traverse((child) => {
      if (!child.isMesh) return
      let node = child
      while (node && node !== root) {
        if (excludeNames.has(node.name)) return
        node = node.parent
      }
      one.setFromObject(child)
      box.union(one)
    })
    return box
  }

  function bindModelGates(model, scale) {
    const found = []
    model.traverse((child) => {
      if (/^Gate_\d+$/i.test(child.name)) found.push(child)
    })
    if (!found.length) return 0

    found.sort((a, b) => a.name.localeCompare(b.name))
    gateMeshes = found.slice(0, DIM.gateCount).map((mesh, index) => {
      // 每个门独立材质，才能做开度高亮而不污染整个模型的材质
      if (mesh.material) {
        mesh.material = Array.isArray(mesh.material)
          ? mesh.material.map((m) => m.clone())
          : mesh.material.clone()
      }
      tmpBox.setFromObject(mesh)
      tmpBox.getSize(tmpSize)
      mesh.userData = {
        baseY: mesh.position.y,
        index,
        procedural: false,
        lift: Math.max(2, tmpSize.y * 0.92),
        emissiveBase: Array.isArray(mesh.material)
          ? mesh.material[0]?.emissive?.clone?.() || null
          : mesh.material?.emissive?.clone?.() || null,
      }
      return mesh
    })
    return gateMeshes.length
  }

  function bindModelWater(model) {
    const surfaces = []
    const worldBox = new THREE.Box3()
    model.updateMatrixWorld(true)
    model.traverse((child) => {
      if (!child.isMesh) return
      if (!/^Water_Surface/i.test(child.name)) return
      child.material = waterMaterial
      child.renderOrder = 2
      // 记录起始局部 Y：模型顶点可能已经带着高程（对象变换为 0），
      // 所以涨落用「起始局部 Y + rise」，两种建模方式都成立
      child.userData.startLocalY = child.position.y
      worldBox.setFromObject(child)
      child.userData.surfaceTopY = worldBox.max.y
      surfaces.push(child)
    })
    if (!surfaces.length) return false

    waterSurfaces.length = 0
    waterSurfaces.push(...surfaces)
    // 程序化大水片让位给"按岸线生成"的模型水面
    water.visible = false
    waterUniforms.uEdgeFade.value = 0

    const reservoir = surfaces.find((s) => /Reservoir/i.test(s.name)) || surfaces[0]
    state.waterBaseY = reservoir.userData.surfaceTopY
    state.waterSurfaces = surfaces.length
    return true
  }

  function bindModelCameras(model) {
    let bound = 0
    for (let i = 0; i < cameras.length; i += 1) {
      const suffix = String(i + 1).padStart(2, '0')
      const point = model.getObjectByName(`CamPoint_${suffix}`)
      if (!point) continue

      point.getWorldPosition(tmpCenter)
      cameras[i].position = [tmpCenter.x, tmpCenter.y, tmpCenter.z]

      // 观察点优先取子空物体 CamTarget_XX（坐标由 glTF 导出器统一转成 Y-up，最稳）
      const targetNode = point.getObjectByName(`CamTarget_${suffix}`)
        || model.getObjectByName(`CamTarget_${suffix}`)
      if (targetNode) {
        const worldTarget = new THREE.Vector3()
        targetNode.getWorldPosition(worldTarget)
        cameras[i].target = [worldTarget.x, worldTarget.y, worldTarget.z]
      }

      const fov = Number(point.userData?.fov)
      if (Number.isFinite(fov) && fov > 10 && fov < 120) cameras[i].fov = fov
      bound += 1
    }
    syncPointMeshes()
    return bound
  }

  /**
   * 载入 Blender 导出的 .glb 小模型
   * @param {string} url
   * @returns {Promise<{ok: boolean, gates: number, cameras: number, water: boolean}>}
   */
  async function loadExternalModel(url) {
    const result = { ok: false, gates: 0, cameras: 0, water: false }
    if (!url) return result

    try {
      const { GLTFLoader } = await import('three/examples/jsm/loaders/GLTFLoader.js')
      const gltf = await new GLTFLoader().loadAsync(url)
      const model = gltf.scene
      model.name = 'blender-dam'

      // 归一化：水平最长边对齐 120 m，X/Z 居中、坝基落地 y=0
      const exclude = new Set()
      const bounds = meshBounds(model, exclude)
      if (bounds.isEmpty()) throw new Error('glb 里没有可用的网格')
      bounds.getSize(tmpSize)
      const rawLength = Math.max(tmpSize.x, tmpSize.z, 1)
      const scale = DIM.damLength / rawLength
      model.scale.setScalar(scale)
      model.updateMatrixWorld(true)

      const scaled = meshBounds(model, exclude)
      model.position.x -= (scaled.min.x + scaled.max.x) / 2
      model.position.z -= (scaled.min.z + scaled.max.z) / 2
      // 带水面的模型（沙盘）自带高程基准：不再把最低点抬到 0，
      // 否则台地/水面/机位会整体偏移，机位 JSON 就对不上了
      const hasWaterDatum = model.getObjectByName('Water_Surface_Reservoir')
        || model.getObjectByName('Water_Surface')
      if (!hasWaterDatum) model.position.y -= scaled.min.y
      model.updateMatrixWorld(true)

      model.traverse((child) => {
        if (child.isMesh) {
          child.castShadow = highQuality
          child.receiveShadow = true
        }
      })

      result.gates = bindModelGates(model, scale)
      result.water = bindModelWater(model)
      scene.add(model)
      result.cameras = bindModelCameras(model)

      // 上游面位置：水光里的坝前泡沫带、告警光环都跟着模型走
      const bodyNode = model.getObjectByName('Dam_Body')
      if (bodyNode) {
        tmpBox.setFromObject(bodyNode)
        state.damX = tmpBox.min.x
        tmpBox.getCenter(tmpCenter)
        tmpBox.getSize(tmpSize)
        alarmRing.position.set(tmpCenter.x, tmpBox.max.y + 0.6, tmpCenter.z)
        // 沙盘尺度下 26 m 的光环会把整块台地圈进去，按坝体尺寸收敛
        state.alarmRingScale = clamp(Math.max(tmpSize.x, tmpSize.z) / 55, 0.18, 1.1)
        alarmRing.scale.setScalar(state.alarmRingScale)
      }

      // 程序化坝体整体让位（含闸墩、门机、指示灯）
      damGroup.visible = false
      state.modelSource = 'blender'
      result.ok = true
      return result
    } catch (err) {
      console.warn('[dam-scene] glb 小模型加载失败，回退到程序化坝体：', err?.message || err)
      return result
    }
  }

  // ───────────────────────── 屏幕投影 ─────────────────────────
  const projected = []
  const tmpVec = new THREE.Vector3()

  function computeScreenPoints(width, height) {
    projected.length = 0
    for (const cam of cameras) {
      tmpVec.set(cam.position[0], cam.position[1] + 2.6, cam.position[2])
      const dist = tmpVec.distanceTo(camera.position)
      tmpVec.project(camera)
      const visible = tmpVec.z > -1 && tmpVec.z < 1
        && Math.abs(tmpVec.x) < 1.35 && Math.abs(tmpVec.y) < 1.35
      projected.push({
        id: cam.id,
        x: (tmpVec.x * 0.5 + 0.5) * width,
        y: (-tmpVec.y * 0.5 + 0.5) * height,
        visible,
        distance: dist,
      })
    }
    return projected
  }

  // ───────────────────────── 主循环 ─────────────────────────
  const clock = new THREE.Clock()
  let raf = 0
  let running = false
  let disposed = false
  let frameAcc = 0
  let frameCount = 0
  let hudTimer = 0

  function tick() {
    if (!running || disposed) return
    raf = requestAnimationFrame(tick)

    const dt = Math.min(0.05, clock.getDelta())
    const elapsed = clock.elapsedTime

    // 水位 / 泡沫 / 告警
    if (waterSurfaces.length) {
      // 模型水面：以设计水位为参考做小幅涨落（沙盘尺度，不做"水位→米制高程"的换算）
      const ref = state.thresholds.design ?? state.thresholds.flood ?? state.thresholds.die
      const targetRise = (ref !== null && state.level !== null)
        ? clamp((state.level - ref) * 0.6, -2.2, 2.2)
        : 0
      state.waterRise = damp(state.waterRise, targetRise, 2.2, dt)
      for (const surface of waterSurfaces) {
        surface.position.y = surface.userData.startLocalY + state.waterRise
      }
      state.waterY = (state.waterBaseY ?? 0) + state.waterRise
      waterUniforms.uLevel01.value = clamp(0.5 + state.waterRise * 0.12, 0, 1)
      // 沙盘尺度的水面不需要几何起伏（1.2 m 网格起伏只会变成刻面），
      // "水光流动"完全由焦散/光带承担
      waterUniforms.uWaveHeight.value = 0.0
      waterUniforms.uFoamWidth.value = 4.5
      waterUniforms.uFoam.value = damp(waterUniforms.uFoam.value, 0.06 + state.foam * 0.34, 2.4, dt)
    } else {
      state.waterY = damp(state.waterY, levelToY(state.level, state.thresholds), 2.6, dt)
      water.position.y = state.waterY
      waterUniforms.uLevel01.value = clamp((state.waterY - 4) / 20, 0, 1)
      waterUniforms.uWaveHeight.value = 0.32 + state.foam * 0.85
      waterUniforms.uFoamWidth.value = 14
      waterUniforms.uFoam.value = damp(waterUniforms.uFoam.value, 0.22 + state.foam * 0.9, 2.4, dt)
    }
    waterUniforms.uDamX.value = state.damX
    waterUniforms.uAlarm.value = damp(waterUniforms.uAlarm.value, state.alarm, 3.2, dt)
    if (state.motion) waterUniforms.uTime.value = elapsed

    // 闸门开度
    let discharge = 0
    for (let i = 0; i < DIM.gateCount; i += 1) {
      gateCurrent[i] = damp(gateCurrent[i], state.gateTargets[i] || 0, 4.5, dt)
      const mesh = gateMeshes[i]
      if (mesh) {
        const lift = mesh.userData.lift || DIM.gateLift
        mesh.position.y = mesh.userData.baseY + gateCurrent[i] * lift
        const isOpen = gateCurrent[i] > 0.5
        const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
        for (const mat of mats) {
          if (!mat) continue
          if (mat.color && !mesh.userData.procedural) {
            // 模型材质只调自发光，保留原色（混凝土/油漆色由美术定）
            if (mat.emissive) {
              mat.emissive.setHex(isOpen ? 0x0d4a5c : 0x000000)
              mat.emissiveIntensity = isOpen ? 0.55 + Math.sin(elapsed * 2) * 0.08 : 0
            }
          } else if (mat.color) {
            mat.color.setHex(isOpen ? 0x2f8fae : 0x7f8f98)
            mat.emissive?.setHex(isOpen ? 0x0d4a5c : 0x000000)
            mat.emissiveIntensity = isOpen ? 0.45 + Math.sin(elapsed * 2) * 0.1 : 0
          }
        }
      }
      discharge += gateCurrent[i]
    }
    discharge /= DIM.gateCount
    state.foam = damp(state.foam, 0.12 + discharge * 0.95, 3, dt)

    // 指示灯（仅程序化模式存在）
    for (let i = 0; i < indicatorGroup.children.length; i += 1) {
      const lamp = indicatorGroup.children[i]
      const isOpen = gateCurrent[i] > 0.5
      lamp.material.color.setHex(isOpen ? 0x35d07f : 0x2f6f52)
      lamp.scale.setScalar(isOpen ? 1.25 + Math.sin(elapsed * 3 + i) * 0.08 : 1)
    }

    // 自动巡视
    if (state.autoTour) {
      state.tourTimer -= dt
      if (state.tourTimer <= 0) {
        state.tourTimer = TOUR_INTERVAL
        const index = state.activePoint ? cameras.findIndex((c) => c.id === state.activePoint) : -1
        const next = cameras[(index + 1) % cameras.length]
        focusPoint(next.id)
        state.autoTour = true
      }
    }

    // 相机飞行 / 阻尼
    if (fly) {
      fly.t += dt / FLY_DURATION
      const t = clamp(fly.t, 0, 1)
      const blended = blendPose(fly.from, fly.to, t)
      pose.target = blended.target
      pose.distance = blended.distance
      pose.azimuth = blended.azimuth
      pose.polar = blended.polar
      fovNow = fly.fovFrom + (fly.fovTo - fly.fovFrom) * t
      if (t >= 1) {
        goal = { ...fly.to, target: [...fly.to.target] }
        fly = null
      }
    } else if (!dragging) {
      pose.azimuth = damp(pose.azimuth, goal.azimuth, 6, dt)
      pose.polar = damp(pose.polar, goal.polar, 6, dt)
      pose.distance = damp(pose.distance, goal.distance, 6, dt)
      pose.target[0] = damp(pose.target[0], goal.target[0], 6, dt)
      pose.target[1] = damp(pose.target[1], goal.target[1], 6, dt)
      pose.target[2] = damp(pose.target[2], goal.target[2], 6, dt)
      fovNow = damp(fovNow, fovGoal, 6, dt)
    }
    applyCamera()

    // 告警光环
    const alarmActive = state.alarm > 0.02
    alarmRing.visible = alarmActive
    if (alarmActive) {
      alarmRing.scale.setScalar(state.alarmRingScale * (1 + Math.sin(elapsed * 2.6) * 0.06))
      alarmRing.material.opacity = 0.18 + state.alarm * 0.5
    }

    // 机位光点
    for (const [id, group] of pointMeshes) {
      const isActive = id === state.activePoint
      const { dot, ring } = group.userData
      const alarmTint = state.alarm > 0.4 ? 0.55 : 0
      dot.material.color.setRGB(
        0.31 * (1 - alarmTint) + alarmTint,
        0.82 * (1 - alarmTint) + 0.16 * alarmTint,
        1 * (1 - alarmTint) + 0.1 * alarmTint,
      )
      dot.material.opacity = isActive ? 1 : 0.75
      dot.scale.setScalar(isActive ? 1.5 + Math.sin(elapsed * 4) * 0.1 : 1)
      ring.scale.setScalar(isActive ? 1.35 + Math.sin(elapsed * 3) * 0.12 : 1)
      ring.material.opacity = isActive ? 0.75 : 0.32
    }

    renderer.render(scene, camera)

    // HUD 投影 ~10Hz，避免 Vue 响应式高频刷新
    hudTimer += dt
    if (hudTimer >= 0.1) {
      hudTimer = 0
      onFrame?.({
        points: computeScreenPoints(host.clientWidth, host.clientHeight),
        fps: state.fps,
        waterY: state.waterY,
        discharge,
        activePoint: state.activePoint,
        calls: renderer.info.render.calls,
        triangles: renderer.info.render.triangles,
        modelSource: state.modelSource,
      })
    }

    frameAcc += dt
    frameCount += 1
    if (frameAcc >= 1) {
      state.fps = Math.round(frameCount / frameAcc)
      frameAcc = 0
      frameCount = 0
    }
  }

  function start() {
    if (running || disposed) return
    running = true
    clock.start()
    raf = requestAnimationFrame(tick)
  }

  function stop() {
    running = false
    cancelAnimationFrame(raf)
  }

  function onVisibilityChange() {
    if (document.hidden) stop()
    else start()
  }
  document.addEventListener('visibilitychange', onVisibilityChange)

  applyCamera()
  renderer.render(scene, camera)

  const dispose = () => {
    disposed = true
    stop()
    document.removeEventListener('visibilitychange', onVisibilityChange)
    resizeObserver?.disconnect()
    canvas.removeEventListener('pointerdown', onPointerDown)
    canvas.removeEventListener('pointermove', onPointerMove)
    canvas.removeEventListener('pointerup', onPointerUp)
    canvas.removeEventListener('pointercancel', onPointerUp)
    canvas.removeEventListener('pointerleave', onPointerUp)
    canvas.removeEventListener('wheel', onWheel)

    scene.traverse((child) => {
      if (child.isMesh || child.isPoints) {
        child.geometry?.dispose?.()
        const mats = Array.isArray(child.material) ? child.material : [child.material]
        for (const mat of mats) {
          if (!mat) continue
          Object.values(mat).forEach((value) => {
            if (value && value.isTexture) value.dispose()
          })
          mat.dispose?.()
        }
      }
    })
    waterGeometry.dispose()
    waterMaterial.dispose()
    renderer.dispose()
    if (canvas.parentNode === host) host.removeChild(canvas)
  }

  /**
   * 把三维坐标投影到容器像素坐标，给 HTML 悬空标签用。
   * visible=false 表示在相机背后或视锥外，标签应隐藏。
   */
  function projectPoint(point) {
    const [x, y, z] = point
    const vector = new THREE.Vector3(x, y, z).project(camera)
    const width = renderer.domElement.clientWidth || host.clientWidth
    const height = renderer.domElement.clientHeight || host.clientHeight
    return {
      x: (vector.x * 0.5 + 0.5) * width,
      y: (-vector.y * 0.5 + 0.5) * height,
      visible: vector.z > -1 && vector.z < 1,
    }
  }

  return {
    setData,
    focusPoint,
    overview,
    setAutoTour,
    setMotion,
    setQuality,
    loadExternalModel,
    resize,
    start,
    stop,
    dispose,
    projectPoint,
    setLabelState,
    state,
    cameras,
    // 调试/美术调参用：直接读写水面 uniform 与网格
    debug: { water, waterMaterial, waterUniforms, waterSurfaces, scene, camera, renderer },
  }
}
