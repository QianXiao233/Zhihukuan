/**
 * 电脑 -> 桥接板 命令帧编码
 *
 * 帧格式： A5 5A | 26 字节 GroundToBoat | 1 字节累加校验
 *
 * mission_state:
 *   0 = 待命
 *   1 = 自主（船端再根据坐标是否有效决定"坐标导航"还是"纯二哈视觉搜救"）
 *   2 = 释放
 *   3 = 返航（船端尚未实现）
 *   4 = 手动遥控
 *
 * release_flag: 1 = 触发投放（船端执行后自行清零，属一次性动作）
 */

/**
 * @param command     当前命令 { armed, mode, throttle, steer, navigation }
 * @param active      是否处于激活状态（超时/未解锁时为 false）
 * @param overrides   可选覆盖 { missionState, releaseFlag }
 *                    用于"释放"这类必须强制覆盖 mission_state 的一次性命令
 */
export function encodeGroundToBoat(command, active, overrides = {}) {
  const navigation = active && command.mode === 'autonomous' ? command.navigation : null;
  const autonomous = active && command.mode === 'autonomous';

  // 注意：自主模式下即使没有坐标也必须置 1，否则船端只会待命，
  //       "二哈识别到就自主前往"这个行为永远不会触发。
  const baseMissionState = autonomous ? 1 : (active && command.mode === 'manual' ? 4 : 0);
  const missionState = overrides.missionState ?? baseMissionState;
  const releaseFlag = overrides.releaseFlag ?? 0;

  // 释放动作期间要停船，不能同时执行手动/自主的推进输出
  const releasing = missionState === 2;

  const data = Buffer.alloc(26);
  data.writeFloatLE(navigation?.boatX ?? 0, 0);
  data.writeFloatLE(navigation?.boatY ?? 0, 4);
  data.writeFloatLE(navigation?.heading ?? 0, 8);
  data.writeFloatLE(navigation?.targetX ?? 0, 12);
  data.writeFloatLE(navigation?.targetY ?? 0, 16);
  data.writeUInt8(missionState, 20);
  data.writeUInt8(releaseFlag, 21);
  data.writeInt16LE(active && !releasing && command.mode === 'manual' ? command.throttle : 0, 22);
  data.writeInt16LE(active && !releasing && command.mode === 'manual' ? command.steer : 0, 24);

  let checksum = 0;
  for (const byte of data) checksum = (checksum + byte) & 0xff;
  return Buffer.concat([Buffer.from([0xa5, 0x5a]), data, Buffer.from([checksum])]);
}
