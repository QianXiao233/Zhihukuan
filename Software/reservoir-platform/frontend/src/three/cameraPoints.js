/**
 * 多点位摄像头定义（全景大坝）
 *
 * 数据源是 cameraPoints.json —— **前端与 Blender 共用同一份**：
 *  - three.js 侧：位置/朝向用于相机飞行与点位光点；
 *  - Blender 侧：build_dam_model.py 读取同一文件生成 CamPoint_XX / CamTarget_XX 空物体，
 *    避免"改了 JS 忘了改模型"这种双份维护。
 *
 * 每个点位的字段含义：
 *  id / code / label / role   HUD 与无障碍标签
 *  position / target          机位与观察点（米，Y 向上，Z 沿坝轴）
 *  fov                        该机位建议视场角，切点位时一并插值
 *  guardian                   是否参与水位告警高亮（溢洪道/闸室/消力池这类过流部位）
 *  stream                     真实视频地址（Janus 流 ID / HLS / FLV）；留空表示"未接入视频"
 */

import RAW from './cameraPoints.json'

function clone(point) {
  return {
    ...point,
    position: [...point.position],
    target: [...point.target],
  }
}

export const CAMERA_POINTS = Object.freeze(RAW.points.map(clone))

/** 总览机位（"全景视角"按钮回到这里） */
export const OVERVIEW_POSE = Object.freeze(clone(RAW.overview))

export function findPoint(id) {
  return CAMERA_POINTS.find((point) => point.id === id) || null
}
