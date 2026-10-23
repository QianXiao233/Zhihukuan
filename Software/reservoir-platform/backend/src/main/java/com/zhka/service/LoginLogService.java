package com.zhka.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * 登录日志。
 *
 * <p>每次登录尝试都落一条记录，成功和失败都记，用于回答「谁在什么时候从哪里登录过」
 * 以及排查撞库来源。与 {@code platform_audit} 分开存：登录发生在鉴权之前，没有管理身份。
 *
 * <p>写入失败只记 warn，绝不抛出——日志是旁路能力，不能影响登录本身。
 */
@Service
public class LoginLogService {

    private static final Logger log = LoggerFactory.getLogger(LoginLogService.class);

    /** 与 login_log 的列宽保持一致，超长直接截断，避免整条记录写不进去。 */
    private static final int MAX_USERNAME = 255;
    private static final int MAX_IP = 64;
    private static final int MAX_REASON = 200;
    private static final int MAX_USER_AGENT = 512;

    private final JdbcTemplate jdbc;

    public LoginLogService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 记录一次登录尝试。
     *
     * @param username  提交的账号（可能是根本不存在的账号，原样记录便于发现撞库）
     * @param ip        客户端 IP，取不到时为空串
     * @param success   是否登录成功
     * @param reason    失败原因；成功时为 null
     * @param userAgent 浏览器 UA，便于区分客户端
     */
    public void record(String username, String ip, boolean success, String reason, String userAgent) {
        try {
            jdbc.update(
                    "INSERT INTO login_log(username, ip, success, reason, user_agent) VALUES (?, ?, ?, ?, ?)",
                    truncate(username, MAX_USERNAME),
                    truncate(ip, MAX_IP),
                    success,
                    truncate(reason, MAX_REASON),
                    truncate(userAgent, MAX_USER_AGENT));
        } catch (Exception ex) {
            log.warn("登录日志写入失败，请检查数据库迁移: {}", ex.getClass().getSimpleName());
        }
    }

    private static String truncate(String value, int max) {
        if (value == null) {
            return null;
        }
        return value.length() <= max ? value : value.substring(0, max);
    }
}
