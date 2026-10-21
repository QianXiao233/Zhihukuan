-- ============================================================
--  平台后端建表脚本（融合后的 server 模块使用）
--  数据库：dam    字符集：utf8mb4
--  执行：mysql -h127.0.0.1 -uroot -p < schema.sql
--
--  说明：dam.user 已存在，此处用 IF NOT EXISTS 保证可重复执行。
-- ============================================================

CREATE DATABASE IF NOT EXISTS dam
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE dam;

-- ── 用户表（登录 / 权限等级） ─────────────────────────────
CREATE TABLE IF NOT EXISTS `user` (
  `ID`       INT          NOT NULL AUTO_INCREMENT,
  `UserName` VARCHAR(255) NOT NULL,
  `PassWord` VARCHAR(255) NOT NULL,
  `Level`    INT          NOT NULL,
  PRIMARY KEY (`ID`),
  UNIQUE KEY `uk_username` (`UserName`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 大坝基础信息 ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `dam_info` (
  `dam_id`             INT           NOT NULL AUTO_INCREMENT,
  `dam_name`           VARCHAR(100)  DEFAULT NULL,
  `dam_type`           VARCHAR(50)   DEFAULT NULL,
  `river_name`         VARCHAR(100)  DEFAULT NULL,
  `location`           VARCHAR(255)  DEFAULT NULL,
  `design_water_level` DECIMAL(10,2) DEFAULT NULL,
  `die_water_level`    DECIMAL(10,2) DEFAULT NULL,
  `flood_water_level`  DECIMAL(10,2) DEFAULT NULL,
  `dam_height`         DECIMAL(10,2) DEFAULT NULL,
  `dam_storage`        DECIMAL(14,2) DEFAULT NULL,
  `control_area`       DECIMAL(12,2) DEFAULT NULL,
  `build_year`         VARCHAR(20)   DEFAULT NULL,
  `status`             INT           DEFAULT 1,
  `remark`             VARCHAR(500)  DEFAULT NULL,
  PRIMARY KEY (`dam_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 已有环境升级：旧版 dam_info 使用 DECIMAL(10,2)，总库容较大时会触发
-- "Out of range value for column dam_storage"。扩大容量字段后保留两位小数。
SET @ddl = IF(EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'dam_info' AND column_name = 'dam_storage'), 'ALTER TABLE dam_info MODIFY COLUMN dam_storage DECIMAL(14,2) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF(EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'dam_info' AND column_name = 'control_area'), 'ALTER TABLE dam_info MODIFY COLUMN control_area DECIMAL(12,2) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ── 设备台账 ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS `dam_device` (
  `device_id`        INT          NOT NULL AUTO_INCREMENT,
  `dam_id`           INT          DEFAULT NULL,
  `device_name`      VARCHAR(100) DEFAULT NULL,
  `device_code`      VARCHAR(100) DEFAULT NULL,
  `device_type`      VARCHAR(50)  DEFAULT NULL,
  `manufacturer`     VARCHAR(100) DEFAULT NULL,
  `model`            VARCHAR(100) DEFAULT NULL,
  `install_time`     DATETIME     DEFAULT NULL,
  `install_position` VARCHAR(255) DEFAULT NULL,
  `protocol`         VARCHAR(50)  DEFAULT NULL,
  `status`           INT          DEFAULT 1,
  `create_time`      DATETIME     DEFAULT CURRENT_TIMESTAMP,
  `update_time`      DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `remark`           VARCHAR(500) DEFAULT NULL,
  PRIMARY KEY (`device_id`),
  KEY `idx_dam_id` (`dam_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 系统参数（阈值上下限） ──────────────────────────────
CREATE TABLE IF NOT EXISTS `dam_system_param` (
  `param_id`         INT          NOT NULL AUTO_INCREMENT,
  `param_code`       VARCHAR(100) DEFAULT NULL,
  `param_name`       VARCHAR(100) DEFAULT NULL,
  `param_low_value`  VARCHAR(50)  DEFAULT NULL,
  `param_high_value` VARCHAR(50)  DEFAULT NULL,
  `param_type`       VARCHAR(50)  DEFAULT NULL,
  `create_time`      DATETIME     DEFAULT CURRENT_TIMESTAMP,
  `remark`           VARCHAR(500) DEFAULT NULL,
  PRIMARY KEY (`param_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 水情日志（MQTT 采集落库） ───────────────────────────
CREATE TABLE IF NOT EXISTS `water_log` (
  `id`          BIGINT       NOT NULL AUTO_INCREMENT,
  `level`       FLOAT        DEFAULT NULL,
  `temperature` FLOAT        DEFAULT NULL,
  `relay1`      INT          DEFAULT NULL,
  `relay2`      INT          DEFAULT NULL,
  `relay3`      INT          DEFAULT NULL,
  `relay4`      INT          DEFAULT NULL,
  `relay5`      INT          DEFAULT NULL,
  `relay6`      INT          DEFAULT NULL,
  `ph`          FLOAT        DEFAULT NULL,
  `orp`         FLOAT        DEFAULT NULL,
  `time`        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_time` (`time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 已有环境执行脚本时，补齐历史 water_log 表的新增字段。
-- 使用 information_schema + PREPARE，兼容 MySQL 8.0.25（不依赖 ADD COLUMN IF NOT EXISTS）。
SET @ddl = IF(EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'water_log' AND column_name = 'relay5'), 'SELECT 1', 'ALTER TABLE water_log ADD COLUMN relay5 INT DEFAULT NULL');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF(EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'water_log' AND column_name = 'relay6'), 'SELECT 1', 'ALTER TABLE water_log ADD COLUMN relay6 INT DEFAULT NULL');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF(EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'water_log' AND column_name = 'ph'), 'SELECT 1', 'ALTER TABLE water_log ADD COLUMN ph FLOAT DEFAULT NULL');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;
SET @ddl = IF(EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = 'water_log' AND column_name = 'orp'), 'SELECT 1', 'ALTER TABLE water_log ADD COLUMN orp FLOAT DEFAULT NULL');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ── 平台消息通知（跨重启持久化） ───────────────────────
CREATE TABLE IF NOT EXISTS `message` (
  `id`          VARCHAR(64)  NOT NULL,
  `level`       INT          NOT NULL DEFAULT 1,
  `type`        VARCHAR(50)  DEFAULT NULL,
  `content`     VARCHAR(1000) NOT NULL,
  `is_read`     TINYINT      NOT NULL DEFAULT 0,
  `create_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_message_read_time` (`is_read`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 默认监测参数（可重复执行，仅在不存在时初始化） ─────
INSERT INTO `dam_system_param` (`param_code`, `param_name`, `param_low_value`, `param_high_value`, `param_type`, `remark`)
SELECT 'water_level', '水位', '0.20', '1.20', '水情', '单位：m'
WHERE NOT EXISTS (SELECT 1 FROM `dam_system_param` WHERE `param_code` = 'water_level');
INSERT INTO `dam_system_param` (`param_code`, `param_name`, `param_low_value`, `param_high_value`, `param_type`, `remark`)
SELECT 'temperature', '液温', '5', '35', '水质', '单位：℃'
WHERE NOT EXISTS (SELECT 1 FROM `dam_system_param` WHERE `param_code` = 'temperature');
INSERT INTO `dam_system_param` (`param_code`, `param_name`, `param_low_value`, `param_high_value`, `param_type`, `remark`)
SELECT 'ph', 'pH', '6.50', '8.50', '水质', '无量纲'
WHERE NOT EXISTS (SELECT 1 FROM `dam_system_param` WHERE `param_code` = 'ph');
INSERT INTO `dam_system_param` (`param_code`, `param_name`, `param_low_value`, `param_high_value`, `param_type`, `remark`)
SELECT 'orp', 'ORP', '-100', '300', '水质', '单位：mV'
WHERE NOT EXISTS (SELECT 1 FROM `dam_system_param` WHERE `param_code` = 'orp');

-- 管理操作审计：不保存密码、令牌及请求正文。
CREATE TABLE IF NOT EXISTS platform_audit (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(255) NOT NULL,
  action VARCHAR(255) NOT NULL,
  target_id VARCHAR(100) DEFAULT NULL,
  success TINYINT NOT NULL DEFAULT 1,
  create_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY idx_audit_time (create_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 阈值告警记录（MySQL；MongoDB 只存水情读数） ─────────
CREATE TABLE IF NOT EXISTS `alert_event` (
  `id`             BIGINT       NOT NULL AUTO_INCREMENT,
  `metric_code`    VARCHAR(50)  NOT NULL,
  `metric_name`    VARCHAR(100) DEFAULT NULL,
  `reading_value`  DOUBLE       DEFAULT NULL,
  `low_threshold`  DOUBLE       DEFAULT NULL,
  `high_threshold` DOUBLE       DEFAULT NULL,
  `unit`           VARCHAR(20)  DEFAULT NULL,
  `direction`      VARCHAR(50)  DEFAULT NULL,
  `status`         VARCHAR(30)  NOT NULL DEFAULT 'queued',
  `pushed`         TINYINT      NOT NULL DEFAULT 0,
  `message`        VARCHAR(500) DEFAULT NULL,
  `alert_time`     DATETIME(3)  NOT NULL,
  `create_time`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_alert_time` (`alert_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- ── 平台键值配置（推送 token / 开关 / 冷却时间等） ───────
-- 这些值以前硬编码在 Java 里，现在改成可在「系统设置 → 推送与告警」维护。
CREATE TABLE IF NOT EXISTS `platform_setting` (
  `setting_key`   VARCHAR(100) NOT NULL,
  `setting_value` TEXT         DEFAULT NULL,
  `update_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`setting_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认值只在不存在时写入，重复执行不会覆盖运维已改过的配置。
-- 安全提示：下面这条 token 是从旧代码里迁移过来的，建议首次登录后在管理页更换。
INSERT INTO `platform_setting` (`setting_key`, `setting_value`)
SELECT 'push.token', '9fa3448690ad0f7a1da7cf509719073f92c761fe516fa1a8ac2a446f0473e642'
WHERE NOT EXISTS (SELECT 1 FROM `platform_setting` WHERE `setting_key` = 'push.token');
INSERT INTO `platform_setting` (`setting_key`, `setting_value`)
SELECT 'push.enabled', 'true'
WHERE NOT EXISTS (SELECT 1 FROM `platform_setting` WHERE `setting_key` = 'push.enabled');
INSERT INTO `platform_setting` (`setting_key`, `setting_value`)
SELECT 'push.cooldown_minutes', '10'
WHERE NOT EXISTS (SELECT 1 FROM `platform_setting` WHERE `setting_key` = 'push.cooldown_minutes');

-- ── 说明：water_log 已降级为「历史数据」 ────────────────
-- 新的水情数据写入 MongoDB 的 water_readings 集合，本表不再写入。
-- 保留它是为了：① 迁移历史数据（管理页「迁移历史数据」按钮 / POST /api/manage/data/migrate）；
-- ② 迁移完成前仍可对照旧数据。确认迁移无误后可自行 DROP（本脚本不会删）。
