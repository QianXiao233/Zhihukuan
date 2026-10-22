package com.zhka.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 消息中转总线配置，前缀 {@code reservoir.bus}。
 *
 * <p>默认值按「告警类消息、低频、可接受至少一次」设定：
 * 租约 2 分钟、最多重试 5 次、消息保留 7 天、单条不超过 64KB、长轮询最多挂 25 秒。
 */
@ConfigurationProperties(prefix = "reservoir.bus")
public class BusProperties {

    /** 领取后的租约（秒）：超时没 ack 会被重新发放 */
    private int leaseSeconds = 120;

    /** 最多领取次数，超过进死信 */
    private int maxAttempts = 5;

    /** 默认消息保留期（秒），7 天 */
    private long defaultTtlSeconds = 604_800;

    /** 允许的最大保留期（秒），30 天 */
    private long maxTtlSeconds = 2_592_000;

    /** 单条消息负载上限（字节） */
    private int maxPayloadBytes = 65_536;

    /** 长轮询最多挂起（秒） */
    private int maxWaitSeconds = 25;

    /** 死信回收任务间隔（秒） */
    private long reaperIntervalSeconds = 30;

    public int getLeaseSeconds() {
        return leaseSeconds;
    }

    public void setLeaseSeconds(int leaseSeconds) {
        this.leaseSeconds = leaseSeconds;
    }

    public int getMaxAttempts() {
        return maxAttempts;
    }

    public void setMaxAttempts(int maxAttempts) {
        this.maxAttempts = maxAttempts;
    }

    public long getDefaultTtlSeconds() {
        return defaultTtlSeconds;
    }

    public void setDefaultTtlSeconds(long defaultTtlSeconds) {
        this.defaultTtlSeconds = defaultTtlSeconds;
    }

    public long getMaxTtlSeconds() {
        return maxTtlSeconds;
    }

    public void setMaxTtlSeconds(long maxTtlSeconds) {
        this.maxTtlSeconds = maxTtlSeconds;
    }

    public int getMaxPayloadBytes() {
        return maxPayloadBytes;
    }

    public void setMaxPayloadBytes(int maxPayloadBytes) {
        this.maxPayloadBytes = maxPayloadBytes;
    }

    public int getMaxWaitSeconds() {
        return maxWaitSeconds;
    }

    public void setMaxWaitSeconds(int maxWaitSeconds) {
        this.maxWaitSeconds = maxWaitSeconds;
    }

    public long getReaperIntervalSeconds() {
        return reaperIntervalSeconds;
    }

    public void setReaperIntervalSeconds(long reaperIntervalSeconds) {
        this.reaperIntervalSeconds = reaperIntervalSeconds;
    }
}
