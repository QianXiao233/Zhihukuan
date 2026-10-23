package com.zhka.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 启动后确保监控画面来源表存在。
 *
 * <p>这张表是视频墙新增的，历史部署的 MySQL 里没有；项目其它表依赖
 * {@code db/schema.sql} / {@code db/management-upgrade.sql} 手工执行，
 * 这里额外做一次幂等兜底，避免升级 jar 后「画面来源」直接 500。
 * 数据库不可用时只记录告警，不影响问答等其它功能启动。
 */
@Component
public class CameraSourceSchemaInitializer {

    private static final Logger log = LoggerFactory.getLogger(CameraSourceSchemaInitializer.class);

    private static final String DDL = """
            CREATE TABLE IF NOT EXISTS camera_source (
              source_id   INT          NOT NULL AUTO_INCREMENT,
              source_name VARCHAR(100) NOT NULL,
              location    VARCHAR(255) DEFAULT NULL,
              protocol    VARCHAR(20)  NOT NULL DEFAULT 'webrtc',
              source_url  VARCHAR(1000) NOT NULL,
              play_url    VARCHAR(1000) DEFAULT NULL,
              gateway_url VARCHAR(500) DEFAULT NULL,
              stream_key  VARCHAR(200) DEFAULT NULL,
              enabled     TINYINT      NOT NULL DEFAULT 1,
              sort_order  INT          NOT NULL DEFAULT 100,
              twin_label  VARCHAR(32)  DEFAULT NULL,
              remark      VARCHAR(500) DEFAULT NULL,
              create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
              update_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
              PRIMARY KEY (source_id),
              UNIQUE KEY uk_camera_twin_label (twin_label),
              KEY idx_camera_enabled_sort (enabled, sort_order)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """;

    private final JdbcTemplate jdbc;

    public CameraSourceSchemaInitializer(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void ensureCameraSourceTable() {
        try {
            jdbc.execute(DDL);
            Integer hasTwinLabel = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM information_schema.columns "
                            + "WHERE table_schema = DATABASE() AND table_name = 'camera_source' "
                            + "AND column_name = 'twin_label'",
                    Integer.class);
            if (hasTwinLabel != null && hasTwinLabel == 0) {
                jdbc.execute("ALTER TABLE camera_source ADD COLUMN twin_label VARCHAR(32) DEFAULT NULL, "
                        + "ADD UNIQUE KEY uk_camera_twin_label (twin_label)");
            }
        } catch (Exception e) {
            log.warn("camera_source 表自动初始化失败，请手工执行 backend/db/management-upgrade.sql：{}", e.getMessage());
        }
    }
}
