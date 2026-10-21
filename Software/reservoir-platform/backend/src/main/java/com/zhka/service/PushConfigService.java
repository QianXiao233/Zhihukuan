package com.zhka.service;

import com.zhka.common.BusinessException;
import com.zhka.config.ReservoirProperties;
import com.zhka.mapper.PlatformSettingMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 推送配置（token / 开关 / 冷却时间）。
 *
 * <p>配置存在 MySQL 的 {@code platform_setting} 表里，可以在管理页修改；
 * 数据库读不到时退回 {@code application.yml} / 环境变量的默认值，
 * 因此「MySQL 没启动」不会让告警链路直接报错，只是改不了配置。
 *
 * <p>token 只在真正发请求时取出，接口对外一律返回掩码（前 6 位 + 后 4 位），
 * 避免管理页的只读接口把完整凭据回显给任何一个登录用户。
 */
@Service
public class PushConfigService {

    private static final Logger log = LoggerFactory.getLogger(PushConfigService.class);

    public static final String KEY_TOKEN = "push.token";
    public static final String KEY_ENABLED = "push.enabled";
    public static final String KEY_COOLDOWN = "push.cooldown_minutes";

    /** 冷却时间上限：一天，超过基本等于「不再推送」 */
    private static final int MAX_COOLDOWN_MINUTES = 1440;

    private final PlatformSettingMapper mapper;
    private final ReservoirProperties properties;

    /** 数据库不可用时的日志节流（毫秒） */
    private volatile long lastFailureLoggedAt = 0L;

    public PushConfigService(PlatformSettingMapper mapper, ReservoirProperties properties) {
        this.mapper = mapper;
        this.properties = properties;
    }

    /** 实际用于发送的 token；数据库优先，其次配置/环境变量 */
    public String token() {
        String stored = read(KEY_TOKEN);
        if (stored != null && !stored.isBlank()) {
            return stored.trim();
        }
        String fallback = properties.getPush().getToken();
        return fallback == null ? "" : fallback.trim();
    }

    /** 推送总开关：配置文件的开关优先关闭，数据库只能在此基础上再关 */
    public boolean enabled() {
        if (!properties.getPush().isEnabled()) {
            return false;
        }
        String stored = read(KEY_ENABLED);
        return stored == null || stored.isBlank() || Boolean.parseBoolean(stored.trim());
    }

    /** 阈值告警冷却时间（分钟），0 表示不限制 */
    public int cooldownMinutes() {
        return clampMinutes(read(KEY_COOLDOWN), properties.getAlert().getCooldownMinutes());
    }

    /** 登录异常告警冷却时间（分钟），只由配置文件控制 */
    public int loginCooldownMinutes() {
        return Math.max(0, Math.min(properties.getAlert().getLoginCooldownMinutes(), MAX_COOLDOWN_MINUTES));
    }

    public boolean alertEnabled() {
        return properties.getAlert().isEnabled();
    }

    /** 管理页展示用：token 打码，不回显完整值 */
    public Map<String, Object> describe() {
        String stored = read(KEY_TOKEN);
        String token = stored != null && !stored.isBlank() ? stored.trim() : token();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("enabled", enabled());
        data.put("alertEnabled", alertEnabled());
        data.put("tokenConfigured", token != null && !token.isBlank());
        data.put("tokenMasked", mask(token));
        data.put("tokenSource", stored != null && !stored.isBlank() ? "database" : "config");
        data.put("cooldownMinutes", cooldownMinutes());
        data.put("loginCooldownMinutes", loginCooldownMinutes());
        data.put("baseUrl", properties.getPush().getBaseUrl());
        data.put("timeoutSeconds", properties.getPush().getTimeout());
        return data;
    }

    /**
     * 保存配置。
     *
     * @param token           新 token；空白表示「保持不变」
     * @param clearToken      true 时清空数据库里的 token（回退到配置文件）
     * @param enabledText     "true"/"false"；null 表示不修改
     * @param cooldownMinutes 冷却分钟数；null 表示不修改
     */
    public void save(String token, boolean clearToken, String enabledText, Integer cooldownMinutes) {
        try {
            if (clearToken) {
                mapper.upsert(KEY_TOKEN, "");
                log.info("[推送] 已清空数据库中的 token，回退到配置文件");
            } else if (token != null && !token.isBlank()) {
                mapper.upsert(KEY_TOKEN, token.trim());
                // 只记长度，不记内容
                log.info("[推送] token 已更新（长度 {}）", token.trim().length());
            }
            if (enabledText != null && !enabledText.isBlank()) {
                boolean enabled = parseBoolean(enabledText);
                mapper.upsert(KEY_ENABLED, String.valueOf(enabled));
            }
            if (cooldownMinutes != null) {
                mapper.upsert(KEY_COOLDOWN, String.valueOf(clampMinutesValue(cooldownMinutes)));
            }
        } catch (Exception e) {
            throw new BusinessException("保存推送配置失败：数据库不可用（" + rootMessage(e) + "）",
                    HttpStatus.SERVICE_UNAVAILABLE);
        }
    }

    /** 管理页展示用的 token 掩码：前 6 位 + 后 4 位 */
    public String mask(String token) {
        if (token == null || token.isBlank()) {
            return "";
        }
        String value = token.trim();
        if (value.length() <= 10) {
            return "******";
        }
        return value.substring(0, 6) + "…" + value.substring(value.length() - 4);
    }

    /** 读数据库；异常时返回 null，并按分钟节流日志 */
    private String read(String key) {
        try {
            return mapper.findValue(key);
        } catch (Exception e) {
            long now = System.currentTimeMillis();
            if (now - lastFailureLoggedAt > 60_000L) {
                lastFailureLoggedAt = now;
                log.debug("[推送] 读取推送配置失败，使用配置文件默认值: {}", rootMessage(e));
            }
            return null;
        }
    }

    private static boolean parseBoolean(String text) {
        String normalized = text.trim().toLowerCase();
        return "1".equals(normalized) || "true".equals(normalized) || "yes".equals(normalized)
                || "on".equals(normalized);
    }

    private static int clampMinutes(String text, int fallback) {
        if (text == null || text.isBlank()) {
            return clampMinutesValue(fallback);
        }
        try {
            return clampMinutesValue(Integer.parseInt(text.trim()));
        } catch (NumberFormatException e) {
            return clampMinutesValue(fallback);
        }
    }

    private static int clampMinutesValue(int value) {
        return Math.max(0, Math.min(value, MAX_COOLDOWN_MINUTES));
    }

    private static String rootMessage(Throwable error) {
        Throwable current = error;
        while (current.getCause() != null && current.getCause() != current) {
            current = current.getCause();
        }
        return current.getMessage() == null ? current.getClass().getSimpleName() : current.getMessage();
    }
}
