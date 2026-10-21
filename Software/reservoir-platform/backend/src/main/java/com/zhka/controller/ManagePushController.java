package com.zhka.controller;

import com.zhka.common.ApiResult;
import com.zhka.service.AuthService;
import com.zhka.service.PushConfigService;
import com.zhka.service.PushCooldownService;
import com.zhka.service.ThresholdMonitorService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 推送配置管理：token、开关、冷却时间与「发一条测试消息」。
 *
 * <p>token 存在 MySQL 的 {@code platform_setting} 表，不再硬编码在代码里；
 * 读取接口只返回掩码，写入接口需要管理员（level 3）。
 */
@RestController
@RequestMapping("/api/manage/push")
public class ManagePushController extends AbstractManageController {

    private final PushConfigService pushConfig;
    private final PushCooldownService cooldown;
    private final ThresholdMonitorService monitor;

    public ManagePushController(AuthService auth, PushConfigService pushConfig,
                                PushCooldownService cooldown, ThresholdMonitorService monitor) {
        super(auth);
        this.pushConfig = pushConfig;
        this.cooldown = cooldown;
        this.monitor = monitor;
    }

    @GetMapping("/config")
    public Map<String, Object> config(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, pushConfig.describe());
    }

    /**
     * 保存配置。token 留空表示「不改」，勾选清除才会把数据库里的 token 置空。
     */
    @PostMapping("/config")
    public Map<String, Object> save(@RequestHeader("Authorization") String authorization,
                                    @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        String cooldownText = params.get("cooldown_minutes");
        Integer cooldownMinutes = null;
        if (cooldownText != null && !cooldownText.isBlank()) {
            try {
                cooldownMinutes = Integer.parseInt(cooldownText.trim());
            } catch (NumberFormatException e) {
                return fail(user, "冷却时间必须是整数分钟（0 表示不限制）");
            }
            if (cooldownMinutes < 0 || cooldownMinutes > 1440) {
                return fail(user, "冷却时间需在 0 ~ 1440 分钟之间");
            }
        }
        boolean clearToken = truthy(params.get("clear_token"));
        pushConfig.save(params.get("token"), clearToken, params.get("enabled"), cooldownMinutes);
        return ApiResult.success("推送配置已保存")
                .withUser(user.username(), user.level())
                .data(pushConfig.describe())
                .toMap();
    }

    /** 发一条测试消息，绕过冷却时间，用来验证 token 是否有效 */
    @PostMapping("/test")
    public Map<String, Object> test(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        var result = monitor.testPush();
        return result.success()
                ? ApiResult.success("测试推送已发送，请检查接收端").withUser(user.username(), user.level())
                        .with("result", result).toMap()
                : ApiResult.failure("测试推送失败：" + result.message()).withUser(user.username(), user.level())
                        .with("result", result).toMap();
    }

    /** 立即解除所有冷却计时（改了阈值或想马上再测一次时用） */
    @PostMapping("/cooldown/reset")
    public Map<String, Object> resetCooldown(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        cooldown.resetAll();
        return ok(user, "已解除全部推送冷却");
    }

    /** 当前冷却剩余秒数，页面轮询展示 */
    @GetMapping("/cooldown")
    public Map<String, Object> cooldown(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, cooldown.snapshot());
    }

    private static boolean truthy(String value) {
        if (value == null) {
            return false;
        }
        String normalized = value.trim().toLowerCase();
        return "1".equals(normalized) || "true".equals(normalized) || "yes".equals(normalized);
    }
}
