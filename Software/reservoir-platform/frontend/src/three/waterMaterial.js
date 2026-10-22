/**
 * 水面材质：水光流动（程序化，零贴图）
 *
 * 为什么不用贴图：
 *  - 老政务内网机器 + 低端核显，加载 4K 水面法线/焦散贴图既慢又占内存；
 *  - 程序化 caustics 只用几条 sin 叠加，视觉上已经足够"水光流动"，
 *    而且可以直接把水位、闸门泄流、告警色当成 uniform 传进来联动。
 *
 * 着色器约定：
 *  - 全部 GLSL 1.0 语法（varying / gl_FragColor），three 在 WebGL2 上也会正确编译；
 *  - 不采样任何纹理，因此没有 sampler 绑定与 MIPMAP 相关问题；
 *  - 顶点只做 3 组正弦波叠加 + 解析法线，面数可控（默认 120×90 段）。
 */

export const WATER_VERTEX_SHADER = /* glsl */ `
uniform float uTime;
uniform float uWaveHeight;

varying vec2 vUv;
varying vec3 vWorldPos;
varying vec3 vNormalW;

// 三组方向/波长/速度都不同的正弦波，叠加出非周期性的水面起伏
float waveHeight(vec2 p, float t) {
  float h = 0.0;
  h += sin(dot(p, normalize(vec2(1.0, 0.32))) * 0.075 + t * 0.85) * 1.0;
  h += sin(dot(p, normalize(vec2(-0.42, 1.0))) * 0.128 + t * 1.30) * 0.62;
  h += sin(dot(p, normalize(vec2(0.68, -0.60))) * 0.215 + t * 1.85) * 0.32;
  return h;
}

void main() {
  vUv = uv;

  vec4 world = modelMatrix * vec4(position, 1.0);
  float h = waveHeight(world.xz, uTime);
  world.y += h * uWaveHeight;
  vWorldPos = world.xyz;

  // 解析法线：对 x / z 各取一次差分，比逐顶点重算法线便宜
  float eps = 0.9;
  float hx = waveHeight(world.xz + vec2(eps, 0.0), uTime);
  float hz = waveHeight(world.xz + vec2(0.0, eps), uTime);
  vec3 tx = normalize(vec3(eps, (hx - h) * uWaveHeight, 0.0));
  vec3 tz = normalize(vec3(0.0, (hz - h) * uWaveHeight, eps));
  vNormalW = normalize(cross(tz, tx));

  gl_Position = projectionMatrix * viewMatrix * world;
}
`

export const WATER_FRAGMENT_SHADER = /* glsl */ `
uniform float uTime;
uniform float uAlarm;
uniform float uFoam;
uniform float uLevel01;
uniform float uDamX;
uniform float uFoamWidth;
uniform float uNight;
uniform float uEdgeFade;
uniform vec3  uDeepColor;
uniform vec3  uShallowColor;
uniform vec3  uSkyColor;
uniform vec3  uSunDir;
uniform vec3  uFogColor;

varying vec2 vUv;
varying vec3 vWorldPos;
varying vec3 vNormalW;

// 多层 sin 叠加的焦散/光斑，随时间横向漂移 -> "水光流动"
float caustic(vec2 p, float t) {
  vec2 q = p * 0.055;
  float c = 0.0;
  c += sin(q.x * 2.10 + t * 0.80) * sin(q.y * 1.70 - t * 0.62);
  c += sin((q.x + q.y) * 1.32 - t * 1.05) * 0.72;
  c += sin(length(q) * 2.35 - t * 1.45) * 0.48;
  return c * 0.25 + 0.5;
}

void main() {
  vec3 N = normalize(vNormalW);
  vec3 V = normalize(cameraPosition - vWorldPos);

  // 菲涅尔：越接近掠射角越像镜面
  float fresnel = pow(1.0 - clamp(dot(N, V), 0.0, 1.0), 3.0);

  // 近坝浅水、远坝深水
  float toDam = abs(vWorldPos.x - uDamX);
  float shallow = smoothstep(26.0, 1.0, toDam);
  vec3 water = mix(uDeepColor, uShallowColor, clamp(shallow * 0.55 + uLevel01 * 0.22, 0.0, 1.0));

  // 天空反射（无环境贴图，用天空色 + 太阳方向近似）
  vec3 R = reflect(-V, N);
  float skyUp = pow(clamp(R.y, 0.0, 1.0), 2.4);
  vec3 skyReflection = mix(uSkyColor, vec3(1.0), skyUp * 0.55);

  // 掠射角处关闭高频细节：否则远处水面会把 caustic/光带压成摩尔纹
  float grazing = clamp(dot(N, V), 0.0, 1.0);
  float detail = smoothstep(0.10, 0.52, grazing);

  // 流动光带：焦散叠两次不同相位，避免看出周期
  float c1 = caustic(vWorldPos.xz + vec2(uTime * 1.15, uTime * 0.55), uTime);
  float c2 = caustic(vWorldPos.xz * 1.7 - vec2(uTime * 0.45, uTime * 0.9), uTime * 1.3);
  float glow = pow(c1 * c2, 1.75);
  water += (uShallowColor * 0.62 + vec3(0.05, 0.06, 0.06)) * glow * 1.55 * detail;

  // 沿风向推进的细长光带：静帧也能看出"水在流"
  float bandPhase = vWorldPos.x * 0.55 + vWorldPos.z * 0.18 - uTime * 2.4;
  float streak = smoothstep(0.62, 1.0, sin(bandPhase) * 0.5 + 0.5);
  float streak2 = smoothstep(0.74, 1.0, sin(bandPhase * 0.53 + 1.7 + uTime * 1.1) * 0.5 + 0.5);
  float streak3 = smoothstep(0.80, 1.0, sin(bandPhase * 0.21 - 0.9 - uTime * 0.7) * 0.5 + 0.5);
  water += uShallowColor * (streak * 0.16 + streak2 * 0.10 + streak3 * 0.08) * detail;

  // 阳光高光（窄高光 -> 水面"碎银"感；外加一圈宽高光做整体反光）
  vec3 H = normalize(uSunDir + V);
  float spec = pow(max(dot(N, H), 0.0), 240.0);
  float sheen = pow(max(dot(N, H), 0.0), 18.0) * 0.16;

  // 坝前泡沫：靠坝越近越明显，叠一层沿坝轴缓慢流动的噪声
  // 带宽 uFoamWidth 可调：大坝场景 14 m，沙盘尺度 4~5 m
  float band = smoothstep(uFoamWidth, 0.5, toDam);
  float ripple = 0.5 + 0.5 * sin(vWorldPos.z * 0.9 + uTime * 1.5 + sin(vWorldPos.x * 1.6 - uTime * 1.1) * 1.2);
  float foam = band * smoothstep(0.62, 0.95, ripple) * uFoam;

  vec3 color = mix(water, skyReflection, fresnel * 0.68);
  color += vec3(1.0, 0.95, 0.84) * (spec * 1.9 + sheen) * (1.0 - uNight * 0.55);
  color = mix(color, vec3(0.90, 0.96, 1.0), foam * 0.85);

  // 告警：只在下游侧近坝区域泛红，不把整片水库染红
  color = mix(color, vec3(0.90, 0.24, 0.18),
              uAlarm * fresnel * smoothstep(70.0, 4.0, toDam) * 0.75);

  // 远远景雾化，和 CSS 背景做出层次
  float dist = length(cameraPosition - vWorldPos);
  float fog = smoothstep(70.0, 260.0, dist);
  color = mix(color, uFogColor, fog * 0.88);

  // 平面边缘淡出（程序化水面用）；模型水面按真实岸线生成，关闭此项
  float edgeFade = smoothstep(0.0, 0.06, vUv.x) * smoothstep(1.0, 0.94, vUv.x)
                 * smoothstep(0.0, 0.06, vUv.y) * smoothstep(1.0, 0.94, vUv.y);
  float alpha = mix(1.0, edgeFade, uEdgeFade);

  gl_FragColor = vec4(color, alpha);
}
`

/**
 * 创建水面材质
 * @param {object} THREE three 命名空间
 * @param {{segments?: number}} [options]
 */
export function createWaterMaterial(THREE, options = {}) {
  const uniforms = {
    uTime: { value: 0 },
    uWaveHeight: { value: 0.55 },
    uAlarm: { value: 0 },
    uFoam: { value: 0.35 },
    uLevel01: { value: 0.5 },
    uDamX: { value: 0 },
    uFoamWidth: { value: 14 },
    uNight: { value: 0.12 },
    uEdgeFade: { value: 1 },
    uDeepColor: { value: new THREE.Color(0x0d5566) },
    uShallowColor: { value: new THREE.Color(0x46d0d8) },
    uSkyColor: { value: new THREE.Color(0xd2f0f7) },
    uSunDir: { value: new THREE.Vector3(-0.53, 0.73, 0.40).normalize() },
    uFogColor: { value: new THREE.Color(0x0b2e38) },
  }

  const material = new THREE.ShaderMaterial({
    uniforms,
    vertexShader: WATER_VERTEX_SHADER,
    fragmentShader: WATER_FRAGMENT_SHADER,
    side: THREE.DoubleSide,
    transparent: true,
    depthWrite: false,
  })
  material.name = 'water-shader'

  return { material, uniforms, segments: options.segments || { x: 140, y: 110 } }
}
