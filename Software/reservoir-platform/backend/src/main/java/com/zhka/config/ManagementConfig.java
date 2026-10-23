package com.zhka.config;

import com.zhka.common.BusinessException;
import com.zhka.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpStatus;
import org.springframework.web.servlet.HandlerInterceptor;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/** 管理接口按数据库中的实时身份校验权限，避免只隐藏前端按钮。 */
@Configuration
public class ManagementConfig implements WebMvcConfigurer {
    private final AuthService auth;
    public ManagementConfig(AuthService auth) { this.auth = auth; }
    public static int requiredLevel(String path, String method) {
        if (path.equals("/api/manage/user/password")) return 1;
        // 通知的已读、全部已读、弹窗确认都是每位登录用户自己的操作
        if (path.equals("/api/manage/messages/read") || path.equals("/api/manage/messages/read-all")
                || path.equals("/api/manage/messages/popup-done")) return 1;
        // 推送 token / 冷却时间：查看给运维（2），修改只给管理员（3）
        if (path.startsWith("/api/manage/push")) return "GET".equals(method) ? 2 : 3;
        // 消息总线的客户端与密钥只给管理员
        if (path.startsWith("/api/manage/bus")) return 3;
        if (path.startsWith("/api/manage/user") || path.startsWith("/api/manage/audit")
                || path.startsWith("/api/manage/login-log")) return 3;
        if ("GET".equals(method)) return 1;
        if (path.startsWith("/api/manage/device") || path.startsWith("/api/manage/param")) return 2;
        return 3;
    }
    @Override public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new HandlerInterceptor() {
            @Override public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
                if ("OPTIONS".equals(request.getMethod())) return true;
                var user = auth.verify(request.getHeader("Authorization"));
                if (user == null) throw new BusinessException("登录已失效，请重新登录", HttpStatus.UNAUTHORIZED);
                if (user.level() == null || (user.level() == 0 ? 3 : user.level()) < requiredLevel(request.getRequestURI(), request.getMethod()))
                    throw new BusinessException("当前账号无权执行此管理操作", HttpStatus.FORBIDDEN);
                request.setAttribute("management.user", user.username());
                return true;
            }
        }).addPathPatterns("/api/manage/**");
    }
}
