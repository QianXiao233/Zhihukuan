/**
 * 视频画面地址解析。
 *
 * <p>浏览器只能播放 WebRTC / HLS，不能直接播放 RTSP。平台约定：
 * <ul>
 *   <li>WebRTC 源：直接填写 WHEP 地址（MediaMTX 的 {@code http://host:8889/<名称>/whep}）。</li>
 *   <li>RTSP 源：填写摄像机 rtsp:// 地址 + 网关地址 + 网关播放标识，
 *       由 MediaMTX / go2rtc 等网关拉流并转成 WebRTC，前端仍走 WHEP。</li>
 *   <li>覆盖播放地址 playUrl 优先级最高，便于接入其它网关。</li>
 * </ul>
 */
export const DEFAULT_VIDEO_GATEWAY = (import.meta.env.VITE_VIDEO_GATEWAY_URL || 'http://127.0.0.1:8889').replace(/\/+$/, '')

function trimSlash(value) {
  return String(value || '').trim().replace(/\/+$/, '')
}

function withWhep(path) {
  return /\/whep$/i.test(path) ? path : `${path}/whep`
}

/**
 * MediaMTX 的网页地址是 {@code http://host:8889/<name>}，WHEP 端点在后面加 {@code /whep}。
 * 已经是完整 WHEP 地址、或带查询参数的地址保持原样。
 */
function normalizeWebRtcUrl(value) {
  const raw = String(value || '').trim()
  if (!raw) return ''
  const url = raw.replace(/\/+$/, '')
  if (url.includes('?')) return url
  if (/\/whep$/i.test(url)) return url
  // 只给形如 http(s)://host:port/<名称> 的 MediaMTX 页面地址补 /whep；
  // 其它带扩展名（.html / .m3u8）的地址不猜。
  if (/^https?:\/\/[^/]+\/[^/.]+$/i.test(url)) return withWhep(url)
  return url
}

/**
 * 计算一路画面最终要连接的 WHEP 地址。
 * @param {Object} source 后端返回的 camera_source 记录
 * @returns {{ url: string, reason: string }} reason 非空表示无法播放及原因
 */
export function resolveWhepUrl(source) {
  if (!source) return { url: '', reason: '画面配置不存在' }
  if (source.playUrl) {
    return { url: normalizeWebRtcUrl(source.playUrl), reason: '' }
  }
  if (source.protocol === 'rtsp') {
    const gateway = trimSlash(source.gatewayUrl) || trimSlash(localStorage.getItem('platform.videoGateway')) || DEFAULT_VIDEO_GATEWAY
    const streamKey = String(source.streamKey || '').trim().replace(/^\/+|\/+$/g, '')
    if (!streamKey) return { url: '', reason: '未配置 RTSP 网关播放标识' }
    return { url: `${gateway}/${streamKey}/whep`, reason: '' }
  }
  const url = normalizeWebRtcUrl(source.sourceUrl)
  if (!url) return { url: '', reason: '未配置 WebRTC 播放地址' }
  return { url, reason: '' }
}

/** 监控页展示用：RTSP 会显示“网关转 WebRTC”提示 */
export function sourceProtocolLabel(source) {
  return source?.protocol === 'rtsp' ? 'RTSP · 网关转 WebRTC' : 'WebRTC · WHEP'
}

export function saveDefaultGateway(gateway) {
  const value = trimSlash(gateway)
  if (value) localStorage.setItem('platform.videoGateway', value)
  else localStorage.removeItem('platform.videoGateway')
}
