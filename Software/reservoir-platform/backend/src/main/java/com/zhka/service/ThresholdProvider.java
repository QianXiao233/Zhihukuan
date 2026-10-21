package com.zhka.service;

import com.zhka.dto.Thresholds;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 阈值读取（带短缓存）。
 *
 * <p>阈值存在 MySQL 的 {@code dam_system_param} 表，而 MQTT 每条上报都要比对；
 * 如果每条都查一次库，高频上报时会把连接池占满。这里缓存 20 秒，
 * 参数页修改阈值后会调用 {@link #invalidate()} 立即失效。
 *
 * <p>MySQL 不可用时保留上一次的有效阈值（没有就全空），不抛异常——
 * 阈值读取失败只应导致「暂时不告警」，不应中断采集。
 */
@Service
public class ThresholdProvider {

    private static final Logger log = LoggerFactory.getLogger(ThresholdProvider.class);

    private static final long TTL_MS = 20_000L;

    private final DamSystemParamService paramService;

    private volatile Thresholds cached = Thresholds.empty();
    private volatile long loadedAt = 0L;
    private volatile long lastFailureLoggedAt = 0L;

    public ThresholdProvider(DamSystemParamService paramService) {
        this.paramService = paramService;
    }

    public Thresholds current() {
        long now = System.currentTimeMillis();
        if (now - loadedAt < TTL_MS) {
            return cached;
        }
        try {
            cached = Thresholds.from(paramService.findAll());
        } catch (Exception e) {
            if (now - lastFailureLoggedAt > 60_000L) {
                lastFailureLoggedAt = now;
                log.debug("[阈值] 读取失败，沿用上一次的阈值: {}", e.getMessage());
            }
        }
        loadedAt = now;
        return cached;
    }

    /** 阈值变更后调用，下次读取立即生效 */
    public void invalidate() {
        loadedAt = 0L;
    }
}
