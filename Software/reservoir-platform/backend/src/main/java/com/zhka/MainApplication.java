package com.zhka;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.autoconfigure.security.servlet.UserDetailsServiceAutoConfiguration;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;

/**
 * 大坝水库数字人智能助手 — 后端服务入口。
 *
 * <p>职责：
 * <ol>
 *   <li>持有 Dify 密钥，向前端暴露统一的 /api 接口（避免密钥落到浏览器）</li>
 *   <li>把 Dify 的 SSE 流归一化成前端约定的 text / navigate / done / error 事件</li>
 *   <li>转发多模态文件到 Dify 的文件上传接口</li>
 *   <li>代理本地 FunASR 语音识别服务</li>
 *   <li>平台侧：登录鉴权、坝体 / 设备 / 参数台账</li>
 * </ol>
 *
 * <p>包结构（按层划分）：
 * {@code controller} → {@code service} → {@code mapper} → {@code entity}，
 * 另有 {@code dto}（传输对象）、{@code config}（配置）、{@code common}（统一响应与异常）、
 * {@code util}（无状态工具）。
 *
 * <p>排除 Spring Security 的默认内存用户自动配置：本项目鉴权走自研 JWT，
 * 保留它只会在启动日志里打印一个用不到的随机密码。
 */
@SpringBootApplication(exclude = UserDetailsServiceAutoConfiguration.class)
@ConfigurationPropertiesScan
public class MainApplication {

    public static void main(String[] args) {
        SpringApplication.run(MainApplication.class, args);
    }
}
