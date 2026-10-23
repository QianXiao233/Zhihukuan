package com.zhka.controller;

import com.zhka.common.ApiResult;
import com.zhka.common.ClientIp;
import com.zhka.service.AuthService;
import com.zhka.service.LoginLogService;
import com.zhka.service.PushCooldownService;
import com.zhka.service.PushConfigService;
import com.zhka.service.PushService;
import com.zhka.service.PushTemplate;
import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.HashMap;
import java.util.Map;

@RestController
@RequestMapping("/auth")
public class AuthController {

    private static final Logger log = LoggerFactory.getLogger(AuthController.class);

    private static final String reason = "用户名或密码不匹配";

    private final PushService pushService;
    private final PushConfigService pushConfig;
    private final PushCooldownService cooldown;
    private final AuthService authService;
    private final LoginLogService loginLog;

    // 单构造器：Spring 自动注入，不需要 @Autowired
    public AuthController(PushService pushService, PushConfigService pushConfig,
                          PushCooldownService cooldown, AuthService authService,
                          LoginLogService loginLog) {
        this.pushService = pushService;
        this.pushConfig = pushConfig;
        this.cooldown = cooldown;
        this.authService = authService;
        this.loginLog = loginLog;
    }

    @PostMapping("/login")
    public Map<String, Object> login(@RequestParam("username") String username,
                                     @RequestParam("enpassword") String enpassword,
                                     HttpServletRequest request) {
        AuthService.LoginResult result = authService.login(username, enpassword);

        // 登录日志：成功与失败都落库，失败原因只存结果消息，不记录口令本身
        loginLog.record(username, ClientIp.resolve(request), result.success(),
                result.success() ? null : result.message(), request.getHeader("User-Agent"));

        ApiResult body;
        if (result.success()) {
            body = ApiResult.success(result.message());
        } else {
            body = ApiResult.failure(result.message());
            notifyLoginAnomaly(username, request);
        }

        if (result.token() != null) {
            body.with("token", result.token());
            var identity = authService.validate(result.token());
            if (identity != null) body.withUser(identity.username(), identity.level());
        }
        return body.toMap();
    }

    /**
     * 登录失败告警。
     *
     * <p>token 从管理页配置（MySQL）读取，不再硬编码；同一账号在冷却窗口内只推一次，
     * 避免爆破脚本把推送通道打爆。
     */
    private void notifyLoginAnomaly(String username, HttpServletRequest request) {
        try {
            if (!pushConfig.enabled()) {
                log.debug("[登录告警] 推送开关已关闭，跳过");
                return;
            }
            String token = pushConfig.token();
            if (token == null || token.isBlank()) {
                log.debug("[登录告警] 未配置推送 token，跳过");
                return;
            }
            int cooldownMinutes = pushConfig.loginCooldownMinutes();
            if (!cooldown.allow("login:" + username, cooldownMinutes)) {
                log.debug("[登录告警] 账号 {} 在冷却期内，跳过推送（{} 分钟）", username, cooldownMinutes);
                return;
            }
            // 用可变 Map，避免 Map.of 遇 null 抛 NPE
            Map<String, Object> payload = new HashMap<>();
            payload.put("username", username);
            payload.put("reason", reason);
            payload.put("ip", ClientIp.resolve(request));
            payload.put("time", LocalDateTime.now()
                    .format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")));
            pushService.pushAsync(token, PushTemplate.LOGIN_ANOMALY_ALERT, payload);
        } catch (Exception e) {
            // 告警失败绝不能影响登录响应
            log.warn("[登录告警] 处理失败: {}", e.getMessage());
        }
    }

    @PostMapping("/register")
    public Map<String, Object> register(@RequestParam("username") String username,
                                        @RequestParam("enpassword") String enpassword,
                                        @RequestParam("Level") Integer level) {
        AuthService.RegisterResult result = authService.register(username, enpassword, 1);
        return (result.success()
                ? ApiResult.success(result.message())
                : ApiResult.failure(result.message())).toMap();
    }

    @PostMapping("/validate")
    public Map<String, Object> validate(@RequestParam("token") String token) {
        AuthService.AuthUser user = authService.validate(token);
        if (user == null) {
            return ApiResult.failure("凭证验证失败!").toMap();
        }
        return ApiResult.success("验证成功！")
                .withUser(user.username(), user.level())
                .toMap();
    }
}
