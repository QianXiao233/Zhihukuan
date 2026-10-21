package com.zhka.controller;

import com.zhka.config.PlatformProperties;
import com.zhka.dto.Thresholds;
import com.zhka.dto.WaterReadingView;
import com.zhka.entity.AlertEvent;
import com.zhka.entity.Metric;
import com.zhka.entity.WaterReading;
import com.zhka.service.AlertService;
import com.zhka.service.AuthService;
import com.zhka.service.PushConfigService;
import com.zhka.service.PushCooldownService;
import com.zhka.service.ThresholdMonitorService;
import com.zhka.service.ThresholdProvider;
import com.zhka.service.WaterReadingService;
import com.zhka.util.TimeParser;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.Clock;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 实时监控状态：最新读数、当前越界项、推送/冷却状态、最近告警。
 *
 * <p>页面上的实时数值仍然优先用浏览器直连 MQTT（延迟低），
 * 这个接口负责回答「后端看到的读数是什么、越界了没有、有没有推出去、为什么没推」。
 */
@RestController
@RequestMapping("/api/manage/monitor")
public class ManageMonitorController extends AbstractManageController {

    /** 告警记录在 MySQL 里存的是平台本地时间，展示时直接格式化 */
    private static final DateTimeFormatter TIME_FORMAT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final ThresholdMonitorService monitor;
    private final ThresholdProvider thresholdProvider;
    private final PushConfigService pushConfig;
    private final PushCooldownService cooldown;
    private final AlertService alertService;
    private final WaterReadingService waterService;
    private final PlatformProperties platform;
    private final Clock clock;

    public ManageMonitorController(AuthService auth, ThresholdMonitorService monitor,
                                   ThresholdProvider thresholdProvider, PushConfigService pushConfig,
                                   PushCooldownService cooldown, AlertService alertService,
                                   WaterReadingService waterService, PlatformProperties platform,
                                   Clock clock) {
        super(auth);
        this.monitor = monitor;
        this.thresholdProvider = thresholdProvider;
        this.pushConfig = pushConfig;
        this.cooldown = cooldown;
        this.alertService = alertService;
        this.waterService = waterService;
        this.platform = platform;
        this.clock = clock;
    }

    @GetMapping("/status")
    public Map<String, Object> status(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }

        Thresholds thresholds = thresholdProvider.current();
        WaterReading latest = monitor.latest();
        if (latest == null) {
            latest = waterService.latestOrNull();
        }

        List<Map<String, Object>> violations = new ArrayList<>();
        if (latest != null) {
            for (Metric metric : Metric.values()) {
                Thresholds.MetricThreshold threshold = thresholds.of(metric);
                Double value = metric.read(latest);
                if (threshold == null || !threshold.configured() || !threshold.violated(value)) {
                    continue;
                }
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("code", metric.code());
                item.put("name", threshold.name());
                item.put("value", value);
                item.put("unit", metric.unit());
                item.put("low", threshold.low());
                item.put("high", threshold.high());
                item.put("threshold", threshold.text());
                item.put("direction", threshold.direction(value));
                violations.add(item);
            }
        }

        Map<String, Object> alert = new LinkedHashMap<>();
        alert.put("alertEnabled", pushConfig.alertEnabled());
        alert.put("pushEnabled", pushConfig.enabled());
        alert.put("tokenConfigured", pushConfig.token() != null && !pushConfig.token().isBlank());
        alert.put("cooldownMinutes", pushConfig.cooldownMinutes());
        alert.put("cooldownRemaining", cooldown.snapshot());
        alert.put("suppressedCount", monitor.suppressedCount());
        alert.put("lastEvaluatedAt", monitor.lastEvaluatedAt());

        List<Map<String, Object>> recentAlerts = new ArrayList<>();
        for (AlertEvent event : alertService.recent(20)) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("id", event.getId());
            item.put("time", event.getTime());
            item.put("timeText", event.getTime() == null ? null
                    : event.getTime().format(TIME_FORMAT));
            item.put("metric", event.getMetricCode());
            item.put("metricName", event.getMetricName());
            item.put("value", event.getReadingValue());
            item.put("unit", event.getUnit());
            item.put("low", event.getLowThreshold());
            item.put("high", event.getHighThreshold());
            item.put("direction", event.getDirection());
            item.put("status", event.getStatus());
            item.put("pushed", event.isPushed());
            item.put("message", event.getMessage());
            recentAlerts.add(item);
        }

        Instant generatedAt = clock.instant();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("latest", WaterReadingView.of(latest, thresholds));
        data.put("latestTimeText", latest == null ? null
                : TimeParser.format(latest.getTime(), platform.zone()));
        data.put("violations", violations);
        data.put("alert", alert);
        data.put("recentAlerts", recentAlerts);
        data.put("stationName", platform.getStationName());
        data.put("generatedAt", generatedAt);
        return okWithData(user, data);
    }
}
