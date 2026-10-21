package com.zhka.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;

/**
 * Spring Security 配置。
 *
 * <p>沿用原平台语义：过滤器链放行全部请求，鉴权由各接口自行校验 JWT
 * （见 {@code AuthService#verify}），因此这里显式关闭 csrf / httpBasic / formLogin，
 * 避免误判「已开启登录页」。
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    /**
     * 预留的密码编码器。
     *
     * <p>当前 {@code user} 表存的是明文口令（登录/注册沿用原有契约），尚未使用本 Bean。
     * 若要启用 BCrypt，需先迁移存量口令并同步改 {@code AuthService}。
     */
    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http) throws Exception {
        http
                .csrf(AbstractHttpConfigurer::disable)
                .httpBasic(AbstractHttpConfigurer::disable)
                .formLogin(AbstractHttpConfigurer::disable)
                .authorizeHttpRequests(registry -> registry.anyRequest().permitAll());
        return http.build();
    }
}
