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
