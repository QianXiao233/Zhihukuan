package com.zhka.service;

import com.zhka.config.PlatformProperties;
import com.zhka.config.ReservoirProperties;
import com.zhka.dto.Thresholds;
import com.zhka.entity.AlertEvent;
import com.zhka.entity.DamSystemParam;
import com.zhka.entity.WaterReading;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/**
 * 实时阈值监控的核心约定：
 * 越界才推、冷却期内不重复推、没配 token 时记录原因但不发请求。
 */
class ThresholdMonitorServiceTest {

    private static final Instant NOW = Instant.parse("2026-10-21T08:00:00Z");

    private ThresholdProvider thresholdProvider;
    private PushConfigService pushConfig;
    private PushService pushService;
    private AlertService alertService;
    private ThresholdMonitorService monitor;

    @BeforeEach
    void setUp() {
        thresholdProvider = mock(ThresholdProvider.class);
        pushConfig = mock(PushConfigService.class);
        pushService = mock(PushService.class);
        alertService = mock(AlertService.class);

        DamSystemParam ph = new DamSystemParam();
        ph.setParamCode("ph");
        ph.setParamName("pH");
        ph.setParamLowValue("6.50");
        ph.setParamHighValue("8.50");
        when(thresholdProvider.current()).thenReturn(Thresholds.from(List.of(ph)));

        when(pushConfig.enabled()).thenReturn(true);
        when(pushConfig.token()).thenReturn("test-token");
        when(pushConfig.cooldownMinutes()).thenReturn(10);

        PlatformProperties platform = new PlatformProperties();
        platform.setStationName("测试水库");
        ReservoirProperties properties = new ReservoirProperties();

        PushCooldownService cooldown = new PushCooldownService(pushConfig, Clock.fixed(NOW, ZoneOffset.UTC));
        monitor = new ThresholdMonitorService(thresholdProvider, pushConfig, pushService, cooldown,
                alertService, platform, properties, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    private static WaterReading reading(Double ph) {
        WaterReading reading = new WaterReading();
        reading.setTime(NOW);
        reading.setLevel(0.3);
        reading.setTemperature(25.0);
        reading.setPh(ph);
        reading.setOrp(56.0);
        return reading;
    }

    @Test
    @SuppressWarnings("unchecked")
    void pushesOnceAndSuppressesWithinCooldown() {
        monitor.evaluate(reading(4.0));

        ArgumentCaptor<Map<String, Object>> variables = ArgumentCaptor.forClass(Map.class);
        verify(pushService, times(1)).pushAsync(eq("test-token"),
                eq(PushTemplate.SENSOR_THRESHOLD_ALERT), variables.capture(), any(Consumer.class));
        assertEquals("pH", variables.getValue().get("metricName"));
        assertEquals("低于下限", variables.getValue().get("direction"));

        // 冷却窗口内的第二次越界：不再调用推送，只累计抑制次数
        monitor.evaluate(reading(4.1));
        verify(pushService, times(1)).pushAsync(any(), any(), anyMap(), any(Consumer.class));
        assertEquals(1L, monitor.suppressedCount());
    }

    @Test
    void doesNotPushWhenReadingIsInsideThreshold() {
        monitor.evaluate(reading(7.0));
        verify(pushService, never()).pushAsync(any(), any(), anyMap(), any(Consumer.class));
        assertEquals(0L, monitor.suppressedCount());
    }

    @Test
    void recordsReasonWhenTokenMissing() {
        when(pushConfig.token()).thenReturn("");

        monitor.evaluate(reading(4.0));

        verify(pushService, never()).pushAsync(any(), any(), anyMap(), any(Consumer.class));
        ArgumentCaptor<AlertEvent> event = ArgumentCaptor.forClass(AlertEvent.class);
        verify(alertService).record(event.capture());
        assertEquals(AlertEvent.STATUS_NO_TOKEN, event.getValue().getStatus());
        assertEquals("ph", event.getValue().getMetricCode());
    }

    @Test
    void recordsSkippedWhenPushDisabled() {
        when(pushConfig.enabled()).thenReturn(false);

        monitor.evaluate(reading(4.0));

        verify(pushService, never()).pushAsync(any(), any(), anyMap(), any(Consumer.class));
        ArgumentCaptor<AlertEvent> event = ArgumentCaptor.forClass(AlertEvent.class);
        verify(alertService).record(event.capture());
        assertEquals(AlertEvent.STATUS_SKIPPED, event.getValue().getStatus());
    }
}
