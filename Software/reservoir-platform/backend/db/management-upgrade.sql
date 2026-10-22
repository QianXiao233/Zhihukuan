USE dam;

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

-- ── 消息总线客户端（MySQL；消息本体在 MongoDB bus_messages） ──
CREATE TABLE IF NOT EXISTS `bus_client` (
  `client_id`       VARCHAR(64)   NOT NULL,
  `client_name`     VARCHAR(100)  NOT NULL,
  `secret_hash`     CHAR(64)      NOT NULL,
  `allow_publish`   VARCHAR(1000) NOT NULL DEFAULT '#',
  `allow_subscribe` VARCHAR(1000) NOT NULL DEFAULT '#',
  `enabled`         TINYINT       NOT NULL DEFAULT 1,
  `created_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`client_id`)
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

-- ── 平台键值配置（推送 token / 开关 / 冷却时间） ─────────
-- 老环境只需要执行本文件即可补齐；schema.sql 里也有一份同样的定义。
CREATE TABLE IF NOT EXISTS `platform_setting` (
  `setting_key`   VARCHAR(100) NOT NULL,
  `setting_value` TEXT         DEFAULT NULL,
  `update_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`setting_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 默认值只在不存在时写入，重复执行不会覆盖运维已改过的配置。
-- 推送 token 不写入版本库：首次部署后到「系统设置 → 推送与告警」填写。
INSERT INTO `platform_setting` (`setting_key`, `setting_value`)
SELECT 'push.token', ''
WHERE NOT EXISTS (SELECT 1 FROM `platform_setting` WHERE `setting_key` = 'push.token');
INSERT INTO `platform_setting` (`setting_key`, `setting_value`)
SELECT 'push.enabled', 'true'
WHERE NOT EXISTS (SELECT 1 FROM `platform_setting` WHERE `setting_key` = 'push.enabled');
INSERT INTO `platform_setting` (`setting_key`, `setting_value`)
SELECT 'push.cooldown_minutes', '10'
WHERE NOT EXISTS (SELECT 1 FROM `platform_setting` WHERE `setting_key` = 'push.cooldown_minutes');

-- ── 用户备注（可重复执行） ───────────────────────────────
SET @ddl = IF(NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'user' AND column_name = 'Remark'),
  'ALTER TABLE `user` ADD COLUMN `Remark` VARCHAR(500) DEFAULT NULL', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ── 通知的弹窗/提示音标记（可重复执行） ─────────────────
SET @ddl = IF(NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'message' AND column_name = 'popup'),
  'ALTER TABLE `message` ADD COLUMN `popup` TINYINT NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @ddl = IF(NOT EXISTS (SELECT 1 FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'message' AND column_name = 'sound'),
  'ALTER TABLE `message` ADD COLUMN `sound` TINYINT NOT NULL DEFAULT 0', 'SELECT 1');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ── 通知接收人：已读/弹窗确认按用户隔离 ─────────────────
CREATE TABLE IF NOT EXISTS `message_recipient` (
  `message_id`  VARCHAR(64)  NOT NULL,
  `username`    VARCHAR(255) NOT NULL,
  `is_read`     TINYINT      NOT NULL DEFAULT 0,
  `popup_done`  TINYINT      NOT NULL DEFAULT 1,
  `read_time`   DATETIME     DEFAULT NULL,
  `create_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`message_id`, `username`),
  KEY `idx_recipient_user` (`username`, `is_read`, `message_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 老通知补接收记录，保证升级后每个人都能看到历史消息；
-- popup_done=1 避免登录时把历史通知全部弹一遍。
INSERT IGNORE INTO `message_recipient` (`message_id`, `username`, `is_read`, `popup_done`, `read_time`)
SELECT m.id, u.UserName, m.is_read, 1, IF(m.is_read = 1, m.create_time, NULL)
FROM `message` m CROSS JOIN `user` u;
