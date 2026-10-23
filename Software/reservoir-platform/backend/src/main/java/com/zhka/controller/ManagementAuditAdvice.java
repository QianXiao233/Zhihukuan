package com.zhka.controller;

import com.zhka.common.ClientIp;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.MethodParameter;
import org.springframework.http.MediaType;
import org.springframework.http.converter.HttpMessageConverter;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.mvc.method.annotation.ResponseBodyAdvice;
import java.util.Map;

/** 只记录管理变更的结果和资源 ID，不记录密码、令牌或表单正文。 */
@RestControllerAdvice
public class ManagementAuditAdvice implements ResponseBodyAdvice<Object> {
    private static final Logger log = LoggerFactory.getLogger(ManagementAuditAdvice.class);
    private final JdbcTemplate jdbc;
    public ManagementAuditAdvice(JdbcTemplate jdbc) { this.jdbc = jdbc; }
    @Override public boolean supports(MethodParameter method, Class<? extends HttpMessageConverter<?>> converter) { return true; }
    @Override public Object beforeBodyWrite(Object body, MethodParameter method, MediaType type,
            Class<? extends HttpMessageConverter<?>> converter, ServerHttpRequest request, ServerHttpResponse response) {
        if (!(request instanceof ServletServerHttpRequest servlet)) return body;
        var req = servlet.getServletRequest();
        if (!req.getRequestURI().startsWith("/api/manage/") || !"POST".equals(req.getMethod()) || req.getAttribute("management.user") == null) return body;
        boolean success = body instanceof Map<?, ?> map && Boolean.TRUE.equals(map.get("success"));
        String target = "";
        for (String key : new String[]{"device_id", "deviceId", "dam_id", "damId", "param_id", "paramId", "id"}) {
            if (req.getParameter(key) != null) { target = req.getParameter(key); break; }
        }
        try {
            jdbc.update("INSERT INTO platform_audit(username, action, target_id, success, ip) VALUES (?, ?, ?, ?, ?)",
                    req.getAttribute("management.user"), req.getRequestURI(), target, success, ClientIp.resolve(req));
        } catch (Exception ex) { log.warn("管理审计写入失败，请检查数据库迁移: {}", ex.getClass().getSimpleName()); }
        return body;
    }
}
