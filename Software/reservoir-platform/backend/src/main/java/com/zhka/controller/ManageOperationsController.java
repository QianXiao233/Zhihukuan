package com.zhka.controller;

import com.zhka.service.AuthService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import java.lang.management.ManagementFactory;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api/manage")
public class ManageOperationsController extends AbstractManageController {
    private static final Logger log = LoggerFactory.getLogger(ManageOperationsController.class);
    private final JdbcTemplate jdbc;
    public ManageOperationsController(AuthService auth, JdbcTemplate jdbc) { super(auth); this.jdbc = jdbc; }
    @GetMapping("/audit/list")
    public Map<String, Object> audit(@RequestHeader("Authorization") String authorization,
            @RequestParam(defaultValue="1") int page, @RequestParam(defaultValue="") String query) {
        var user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        int offset = (Math.max(1, Math.min(page, 100000)) - 1) * 20;
        String pattern = "%" + query + "%";
        var rows = auditRows(pattern, offset);
        long total = jdbc.queryForObject("SELECT COUNT(*) FROM platform_audit WHERE username LIKE ? OR action LIKE ?", Long.class, pattern, pattern);
        return okWithData(user, Map.of("rows", rows, "total", total));
    }

    /**
     * 读操作日志。
     *
     * <p>老环境如果还没执行 {@code db/management-upgrade.sql}，{@code ip} 列不存在，
     * 直接查询会让整个页面 500。这里退回到不含 ip 的旧查询，只丢一列而不是丢整个页面。
     */
    private List<Map<String, Object>> auditRows(String pattern, int offset) {
        try {
            return jdbc.queryForList("SELECT id, username, action, target_id AS targetId, success, ip, region, create_time AS createTime FROM platform_audit WHERE username LIKE ? OR action LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", pattern, pattern, offset);
        } catch (DataAccessException ex) {
            log.warn("platform_audit 缺少 region 列，已退回不含地区的查询；请执行 db/management-upgrade.sql");
            try {
                return jdbc.queryForList("SELECT id, username, action, target_id AS targetId, success, ip, create_time AS createTime FROM platform_audit WHERE username LIKE ? OR action LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", pattern, pattern, offset);
            } catch (DataAccessException ex2) {
                log.warn("platform_audit 缺少 ip 列，已退回旧查询；请在服务器执行 db/management-upgrade.sql");
                return jdbc.queryForList("SELECT id, username, action, target_id AS targetId, success, create_time AS createTime FROM platform_audit WHERE username LIKE ? OR action LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", pattern, pattern, offset);
            }
        }
    }

    /**
     * 登录日志：成功与失败都记录，可按账号或 IP 检索。
     *
     * <p>与操作日志分开：登录发生在鉴权之前，没有管理身份，失败记录的账号甚至可能不存在。
     */
    @GetMapping("/login-log/list")
    public Map<String, Object> loginLog(@RequestHeader("Authorization") String authorization,
            @RequestParam(defaultValue="1") int page, @RequestParam(defaultValue="") String query) {
        var user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        int offset = (Math.max(1, Math.min(page, 100000)) - 1) * 20;
        String pattern = "%" + query + "%";
        try {
            var rows = jdbc.queryForList("SELECT id, username, ip, region, success, reason, user_agent AS userAgent, create_time AS createTime FROM login_log WHERE username LIKE ? OR ip LIKE ? OR region LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", pattern, pattern, pattern, offset);
            long total = jdbc.queryForObject("SELECT COUNT(*) FROM login_log WHERE username LIKE ? OR ip LIKE ? OR region LIKE ?", Long.class, pattern, pattern, pattern);
            return okWithData(user, Map.of("rows", rows, "total", total));
        } catch (DataAccessException ex) {
            // 兼容还没补 region 列的环境；表完全不存在时再给出迁移提示
            try {
                var rows = jdbc.queryForList("SELECT id, username, ip, success, reason, user_agent AS userAgent, create_time AS createTime FROM login_log WHERE username LIKE ? OR ip LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", pattern, pattern, offset);
                long total = jdbc.queryForObject("SELECT COUNT(*) FROM login_log WHERE username LIKE ? OR ip LIKE ?", Long.class, pattern, pattern);
                return okWithData(user, Map.of("rows", rows, "total", total));
            } catch (DataAccessException ex2) {
                log.warn("login_log 表不存在；请在服务器执行 db/management-upgrade.sql");
                return fail(user, "登录日志表尚未创建，请先在服务器执行 backend/db/management-upgrade.sql");
            }
        }
    }
    @GetMapping("/runtime")
    public Map<String, Object> runtime(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("uptimeSeconds", ManagementFactory.getRuntimeMXBean().getUptime() / 1000);
        data.put("serverTime", java.time.LocalDateTime.now().toString());
        data.put("database", jdbc.queryForObject("SELECT 1", Integer.class) == 1);
        data.put("deviceCount", jdbc.queryForObject("SELECT COUNT(*) FROM dam_device", Long.class));
        data.put("waterLogCount", jdbc.queryForObject("SELECT COUNT(*) FROM water_log", Long.class));
        data.put("notificationCount", jdbc.queryForObject("SELECT COUNT(*) FROM message", Long.class));
        data.put("latestCollection", jdbc.queryForObject("SELECT MAX(time) FROM water_log", java.sql.Timestamp.class));
        return okWithData(user, data);
    }
}
