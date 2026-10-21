import assert from 'node:assert/strict';
import { encodeGroundToBoat } from './protocol.js';

const navigation = { boatX: 0.2, boatY: 0.3, heading: 90, targetX: 1.1, targetY: 0.9 };

const autonomous = encodeGroundToBoat({ mode: 'autonomous', navigation, throttle: 180, steer: -50 }, true);
assert.deepEqual([...autonomous.subarray(0, 2)], [0xa5, 0x5a]);
assert.equal(autonomous.length, 29);
assert.ok(Math.abs(autonomous.readFloatLE(2) - navigation.boatX) < 1e-6);
assert.ok(Math.abs(autonomous.readFloatLE(6) - navigation.boatY) < 1e-6);
assert.ok(Math.abs(autonomous.readFloatLE(10) - navigation.heading) < 1e-6);
assert.ok(Math.abs(autonomous.readFloatLE(14) - navigation.targetX) < 1e-6);
assert.ok(Math.abs(autonomous.readFloatLE(18) - navigation.targetY) < 1e-6);
assert.equal(autonomous.readUInt8(22), 1);
assert.equal(autonomous.readInt16LE(24), 0);
assert.equal(autonomous.readInt16LE(26), 0);
assert.equal(autonomous[28], autonomous.subarray(2, 28).reduce((sum, byte) => (sum + byte) & 0xff, 0));

const manual = encodeGroundToBoat({ mode: 'manual', throttle: 80, steer: -30 }, true);
assert.equal(manual.readUInt8(22), 4);
assert.equal(manual.readInt16LE(24), 80);
assert.equal(manual.readInt16LE(26), -30);

const idle = encodeGroundToBoat({ mode: 'manual', throttle: 80, steer: -30 }, false);
assert.equal(idle.readUInt8(22), 0);
assert.equal(idle.readInt16LE(24), 0);
assert.equal(idle.readInt16LE(26), 0);

// --- 二哈自主搜救：自主模式但没有坐标，仍须发 mission_state=1 ---
// 若这里退回 0，船端只会待命，"识别到就自主前往"永远不会触发。
const visionOnly = encodeGroundToBoat({ mode: 'autonomous', navigation: null }, true);
assert.equal(visionOnly.readUInt8(22), 1, 'autonomous 无坐标时 mission_state 必须为 1');
assert.equal(visionOnly.readFloatLE(2), 0);
assert.equal(visionOnly.readFloatLE(6), 0);
assert.equal(visionOnly.readFloatLE(10), 0);
assert.equal(visionOnly.readFloatLE(14), 0);
assert.equal(visionOnly.readFloatLE(18), 0);

// 未激活时必须回到待命
const visionOnlyIdle = encodeGroundToBoat({ mode: 'autonomous', navigation: null }, false);
assert.equal(visionOnlyIdle.readUInt8(22), 0, '未解锁时 mission_state 必须为 0');

// --- 投放释放：必须覆盖 mission_state=2 且停船 ---
// 即使当前是手动模式且油门给满，释放期间也必须停船，否则会边冲边投。
const release = encodeGroundToBoat(
  { mode: 'manual', throttle: 200, steer: -100, navigation: null },
  true,
  { missionState: 2, releaseFlag: 1 },
);
assert.equal(release.readUInt8(22), 2, '释放时 mission_state 必须为 2');
assert.equal(release.readUInt8(23), 1, '释放时 release_flag 必须为 1');
assert.equal(release.readInt16LE(24), 0, '释放时必须停船（throttle=0）');
assert.equal(release.readInt16LE(26), 0, '释放时必须停船（steer=0）');

// 释放不可覆盖为待命：overrides 优先级高于 active/mode
const releaseWhileDisarmed = encodeGroundToBoat(
  { mode: 'manual', throttle: 0, steer: 0, navigation: null },
  false,
  { missionState: 2, releaseFlag: 1 },
);
assert.equal(releaseWhileDisarmed.readUInt8(22), 2);

// 未释放时 release_flag 必须为 0（否则船端会重复投放）
const noRelease = encodeGroundToBoat({ mode: 'manual', throttle: 50, steer: 0 }, true);
assert.equal(noRelease.readUInt8(23), 0, '非释放帧 release_flag 必须为 0');

console.log('protocol.test.js: 全部断言通过');
