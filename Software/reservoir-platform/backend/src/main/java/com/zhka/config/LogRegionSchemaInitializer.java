package com.zhka.config;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

/**
 * 给已有的登录日志、管理审计补 region 列。
 *
 * <p>新环境由 db/schema.sql 建表；已经上线的环境不能保证有人手动执行 SQL，
 * 所以启动时做一次幂等检查，缺列就补，失败只告警不阻塞启动。
 */
@Component
public class LogRegionSchemaInitializer {

    private static final Logger log = LoggerFactory.getLogger(LogRegionSchemaInitializer.class);

    private final JdbcTemplate jdbc;

    public LogRegionSchemaInitializer(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void init() {
        addRegion("platform_audit");
        addRegion("login_log");
    }

    private void addRegion(String table) {
        try {
            Integer tableCount = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = ?",
                    Integer.class, table);
            if (tableCount == null || tableCount == 0) {
                return;
            }
            Integer columnCount = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = DATABASE() AND table_name = ? AND column_name = 'region'",
                    Integer.class, table);
            if (columnCount != null && columnCount > 0) {
                return;
            }
            try {
                jdbc.execute("ALTER TABLE `" + table + "` ADD COLUMN region VARCHAR(100) DEFAULT NULL AFTER ip");
            } catch (Exception afterIpFailed) {
                // 极老环境可能连 ip 列都没有，退化为加在表尾
                jdbc.execute("ALTER TABLE `" + table + "` ADD COLUMN region VARCHAR(100) DEFAULT NULL");
            }
            log.info("已为 {} 补充 region 列", table);
        } catch (Exception ex) {
            log.warn("为 {} 补充 region 列失败，请检查数据库迁移: {}", table, ex.getClass().getSimpleName());
        }
    }
}
