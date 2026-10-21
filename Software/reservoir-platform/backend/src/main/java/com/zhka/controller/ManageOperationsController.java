package com.zhka.controller;

import com.zhka.service.AuthService;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import java.lang.management.ManagementFactory;
import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/manage")
public class ManageOperationsController extends AbstractManageController {
    private final JdbcTemplate jdbc;
    public ManageOperationsController(AuthService auth, JdbcTemplate jdbc) { super(auth); this.jdbc = jdbc; }
    @GetMapping("/audit/list")
    public Map<String, Object> audit(@RequestHeader("Authorization") String authorization,
            @RequestParam(defaultValue="1") int page, @RequestParam(defaultValue="") String query) {
        var user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        int offset = (Math.max(1, Math.min(page, 100000)) - 1) * 20;
        String pattern = "%" + query + "%";
        var rows = jdbc.queryForList("SELECT id, username, action, target_id AS targetId, success, create_time AS createTime FROM platform_audit WHERE username LIKE ? OR action LIKE ? ORDER BY id DESC LIMIT 20 OFFSET ?", pattern, pattern, offset);
        long total = jdbc.queryForObject("SELECT COUNT(*) FROM platform_audit WHERE username LIKE ? OR action LIKE ?", Long.class, pattern, pattern);
        return okWithData(user, Map.of("rows", rows, "total", total));
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
