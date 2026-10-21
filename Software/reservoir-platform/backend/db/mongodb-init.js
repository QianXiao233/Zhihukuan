// 可选：手动初始化 MongoDB 集合与索引。
//
// 应用在首次写入时会自动创建同样的索引（WaterReadingQueryRepository#ensureIndexes），
// 这个脚本只用于「想先建好库再启动应用」或排查索引问题的场景。
//
// 注意：MongoDB 只存水情读数（water_readings）。
// 登录、台账、阈值、消息、告警记录、推送配置都在 MySQL，本脚本不建这些集合。
//
// 执行：mongosh "mongodb://127.0.0.1:27017/dam" backend/db/mongodb-init.js

const database = db.getSiblingDB('dam');

// 水情读数
if (!database.getCollectionNames().includes('water_readings')) {
  database.createCollection('water_readings');
}
database.water_readings.createIndex({ time: -1 }, { name: 'idx_time' });
// 迁移幂等：旧 MySQL 主键唯一；非迁移数据没有该字段，用稀疏索引跳过
database.water_readings.createIndex(
  { legacyId: 1 },
  { name: 'uniq_legacy_id', unique: true, sparse: true }
);

print('MongoDB 初始化完成（仅水情数据）：');
printjson(database.water_readings.getIndexes());
