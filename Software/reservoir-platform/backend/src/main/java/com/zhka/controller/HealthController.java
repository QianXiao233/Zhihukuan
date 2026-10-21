package com.zhka.controller;

import com.zhka.config.ReservoirProperties;
import com.zhka.dto.HealthData;
import com.zhka.service.AsrService;
import com.zhka.service.DifyService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

/**
 * 健康检查：{@code GET /health}。
 *
 * <p>原实现同时挂载了语音识别接口，已拆分到 {@link AsrController}，本类只做健康探测。
 */
@RestController
public class HealthController {

    private final DifyService difyService;
    private final AsrService asrService;
    private final ReservoirProperties properties;

    public HealthController(DifyService difyService, AsrService asrService, ReservoirProperties properties) {
        this.difyService = difyService;
        this.asrService = asrService;
        this.properties = properties;
    }

    @GetMapping("/health")
    public Mono<HealthData> health() {
        return asrService.ping().map(asrAvailable -> new HealthData(
                "ok",
                difyService.getApiBase(),
                difyService.isKeyConfigured(),
                asrAvailable,
                properties.getTts().getProvider()));
    }
}
