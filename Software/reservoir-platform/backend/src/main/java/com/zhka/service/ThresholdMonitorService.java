package com.zhka.service;

import com.zhka.config.PlatformProperties;
import com.zhka.config.ReservoirProperties;
import com.zhka.dto.Thresholds;
import com.zhka.entity.AlertEvent;
import com.zhka.entity.Metric;
import com.zhka.entity.WaterReading;
import com.zhka.util.TimeParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 实时阈值监控：每收到一条水情数据就比对阈值，越界则推送。
 *
 * <p>流程：
 * <ol>
 *   <li>按指标（水位 / 液温 / pH / ORP）逐个比对上下限；</li>
 *   <li>越界时先过冷却时间：同一指标在窗口内只推一次（{@link PushCooldownService}）；</li>
 *   <li>通过冷却检查后异步推送，推送结果异步回写到 MySQL 的 {@code alert_event}；</li>
 *   <li>关闭推送开关或没配 token 时，仍然记录一条「未推送」的告警，页面能看到原因。</li>
 * </ol>
 *
 * <p>异常隔离：这个类运行在 MQTT 回调线程里，任何异常都只记日志，
 * 不能把采集线程带崩。
 */
@Service
public class ThresholdMonitorService {

    private static final Logger log = LoggerFactory.getLogger(ThresholdMonitorService.class);

    private final ThresholdProvider thresholdProvider;
    private final PushConfigService pushConfig;
    private final PushService pushService;
    private final PushCooldownService cooldown;
    private final AlertService alertService;
    private final PlatformProperties platform;
    private final ReservoirProperties properties;
    private final Clock clock;

    /** 冷却期内被抑制的告警次数（进程级累计，用于页面展示） */
    private final AtomicLong suppressed = new AtomicLong();

    private volatile WaterReading latest;
    private volatile Instant lastEvaluatedAt;

    public ThresholdMonitorService(ThresholdProvider thresholdProvider,
                                   PushConfigService pushConfig,
                                   PushService pushService,
                                   PushCooldownService cooldown,
                                   AlertService alertService,
                                   PlatformProperties platform,
                                   ReservoirProperties properties,
                                   Clock clock) {
        this.thresholdProvider = thresholdProvider;
        this.pushConfig = pushConfig;
        this.pushService = pushService;
        this.cooldown = cooldown;
        this.alertService = alertService;
        this.platform = platform;
        this.properties = properties;
        this.clock = clock;
    }

    /** 入口：比对一条读数 */
    public void evaluate(WaterReading reading) {
        if (reading == null) {
            return;
        }
        latest = reading;
        lastEvaluatedAt = clock.instant();
        if (!properties.getAlert().isEnabled()) {
            return;
        }
        try {
            Thresholds thresholds = thresholdProvider.current();
            Instant time = reading.getTime() == null ? clock.instant() : reading.getTime();
            for (Metric metric : Metric.values()) {
                Thresholds.MetricThreshold threshold = thresholds.of(metric);
                Double value = metric.read(reading);
                if (threshold == null || !threshold.configured() || !threshold.violated(value)) {
                    continue;
                }
                handleViolation(metric, threshold, value, time);
            }
        } catch (Exception e) {
            log.warn("[告警] 阈值比对失败: {}", e.getMessage());
        }
    }

    private void handleViolation(Metric metric, Thresholds.MetricThreshold threshold,
                                 Double value, Instant time) {
        String key = "metric:" + metric.code();
        if (!cooldown.allow(key)) {
            suppressed.incrementAndGet();
            log.debug("[告警] {} 越界，但在冷却期内，跳过推送（值 {}）", metric.label(), value);
            return;
        }

        AlertEvent event = new AlertEvent();
        event.setTime(LocalDateTime.ofInstant(time, platform.zone()));
        event.setMetricCode(metric.code());
        event.setMetricName(threshold.name());
        event.setReadingValue(value);
        event.setLowThreshold(threshold.low());
        event.setHighThreshold(threshold.high());
        event.setUnit(metric.unit());
        event.setDirection(threshold.direction(value));

        if (!pushConfig.enabled()) {
            event.setStatus(AlertEvent.STATUS_SKIPPED);
            event.setMessage("推送开关已关闭");
            alertService.record(event);
            log.info("[告警] {} 越界（值 {}），推送开关已关闭，未发送", metric.label(), value);
            return;
        }
        String token = pushConfig.token();
        if (token == null || token.isBlank()) {
            event.setStatus(AlertEvent.STATUS_NO_TOKEN);
            event.setMessage("未配置推送 token");
            alertService.record(event);
            log.warn("[告警] {} 越界（值 {}），但未配置推送 token，未发送", metric.label(), value);
            return;
        }

        event.setStatus(AlertEvent.STATUS_QUEUED);
        pushService.pushAsync(token, PushTemplate.SENSOR_THRESHOLD_ALERT, variables(metric, threshold, value, time),
                result -> {
                    event.setPushed(result.success());
                    event.setStatus(result.success() ? AlertEvent.STATUS_SENT : AlertEvent.STATUS_FAILED);
                    event.setMessage(result.message());
                    alertService.record(event);
                    if (!result.success()) {
                        log.warn("[告警] 推送失败 metric={} 原因={}", metric.code(), result.message());
                    }
                });
    }

    private Map<String, Object> variables(Metric metric, Thresholds.MetricThreshold threshold,
                                          Double value, Instant time) {
        Map<String, Object> variables = new LinkedHashMap<>();
        variables.put("station", platform.getStationName());
        variables.put("metricName", threshold.name());
        variables.put("currentValue", format(value, metric.digits()));
        variables.put("unit", metric.unit());
        variables.put("threshold", threshold.text());
        variables.put("direction", threshold.direction(value));
        variables.put("time", TimeParser.format(time, platform.zone()));
        return variables;
    }

    /** 手工发一条测试推送，绕过冷却时间，用于验证 token 是否可用 */
    public PushService.PushResult testPush() {
        String token = pushConfig.token();
        if (token == null || token.isBlank()) {
            return PushService.PushResult.fail(0, "未配置推送 token，请先在上方填写并保存");
        }
        if (!pushConfig.enabled()) {
            return PushService.PushResult.fail(0, "推送开关已关闭");
        }
        Map<String, Object> variables = new LinkedHashMap<>();
        variables.put("station", platform.getStationName());
        variables.put("metricName", "水位");
        variables.put("currentValue", "1.35");
        variables.put("unit", "m");
        variables.put("threshold", "0.20 ~ 1.20 m");
        variables.put("direction", "高于上限");
        variables.put("time", TimeParser.format(clock.instant(), platform.zone()));
        return pushService.push(token, PushTemplate.SENSOR_THRESHOLD_ALERT, variables);
    }

    public WaterReading latest() {
        return latest;
    }

    public Instant lastEvaluatedAt() {
        return lastEvaluatedAt;
    }

    public long suppressedCount() {
        return suppressed.get();
    }

    private static String format(Double value, int digits) {
        if (value == null) {
            return "—";
        }
        return String.format("%." + Math.max(0, digits) + "f", value);
    }
}
