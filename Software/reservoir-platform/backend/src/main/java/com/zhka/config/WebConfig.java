package com.zhka.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 层配置：统一跨域。
 *
 * <p>本项目是 Servlet（Spring MVC）应用——同时引入了 webflux 只是为了用
 * {@code WebClient} 调 Dify，因此必须实现 {@link WebMvcConfigurer}；
 * 原实现用的是 {@code WebFluxConfigurer}，在 MVC 下不会被加载，跨域配置实际不生效。
 *
 * <p>放行范围：本机 + 常见内网网段。前端若用绝对地址直连后端（例如
 * {@code reservoir-platform/frontend} 走 vite 代理是同源，而 {@code zyal_vue} 是 {@code fetch} 直连），
 * 浏览器会做跨域校验，来源不在名单里就会被拦（预检返回 403）。
 *
 * <p>换网络环境（比如内网改成 {@code 172.16.x.x} 或上了域名）时不必改代码，
 * 用环境变量覆盖即可，逗号分隔：
 * <pre>
 *   APP_CORS_ALLOWED_ORIGIN_PATTERNS=http://localhost:*,http://192.168.*:*,https://dam.example.com
 * </pre>
 * 生产环境建议前后端同域部署，并把这里收紧成确定的域名。
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final String[] allowedOriginPatterns;

    public WebConfig(
            @Value("${app.cors.allowed-origin-patterns:"
                    + "http://localhost:*,http://127.0.0.1:*,http://192.168.*:*,http://10.*:*}")
            String[] allowedOriginPatterns) {
        this.allowedOriginPatterns = allowedOriginPatterns;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                .allowedOriginPatterns(allowedOriginPatterns)
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .maxAge(3600);
    }
}
