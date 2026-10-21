package com.zhka.service;

import org.junit.jupiter.api.Test;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.time.ZoneOffset;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * 冷却时间的行为约定：窗口内只放行一次，窗口到期后重新放行，
 * 不同 key（不同指标）互不影响，0 分钟表示不限制。
 */
class PushCooldownServiceTest {

    /** 可手动推进的时钟，避免测试里 sleep */
    private static final class MutableClock extends Clock {

        private Instant instant;

        private MutableClock(Instant instant) {
            this.instant = instant;
        }

        void plus(Duration duration) {
            instant = instant.plus(duration);
        }

        @Override
        public ZoneId getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }
    }

    private static PushConfigService config(int minutes) {
        PushConfigService config = mock(PushConfigService.class);
        when(config.cooldownMinutes()).thenReturn(minutes);
        return config;
    }

    @Test
    void suppressesWithinWindowAndAllowsAgainWhenWindowExpires() {
        MutableClock clock = new MutableClock(Instant.parse("2026-10-21T08:00:00Z"));
        PushCooldownService service = new PushCooldownService(config(10), clock);

        assertTrue(service.allow("metric:ph"), "第一次应当放行");
        assertFalse(service.allow("metric:ph"), "窗口内第二次应当被抑制");
        assertEquals(600, service.remainingSeconds("metric:ph"));

        clock.plus(Duration.ofMinutes(5));
        assertFalse(service.allow("metric:ph"), "5 分钟后仍在窗口内");
        assertEquals(300, service.remainingSeconds("metric:ph"));

        clock.plus(Duration.ofMinutes(5));
        assertTrue(service.allow("metric:ph"), "窗口到期后应重新放行");
        // 重新放行意味着开启了新的冷却窗口，剩余时间回到满额
        assertEquals(600, service.remainingSeconds("metric:ph"));
    }

    @Test
    void differentKeysAreIndependent() {
        MutableClock clock = new MutableClock(Instant.parse("2026-10-21T08:00:00Z"));
        PushCooldownService service = new PushCooldownService(config(10), clock);

        assertTrue(service.allow("metric:ph"));
        assertTrue(service.allow("metric:water_level"), "另一个指标不应被 pH 的冷却影响");
        assertFalse(service.allow("metric:ph"));
    }

    @Test
    void zeroMinutesMeansNoLimit() {
        MutableClock clock = new MutableClock(Instant.parse("2026-10-21T08:00:00Z"));
        PushCooldownService service = new PushCooldownService(config(0), clock);

        assertTrue(service.allow("metric:ph"));
        assertTrue(service.allow("metric:ph"));
        assertEquals(0, service.remainingSeconds("metric:ph"));
    }

    @Test
    void resetClearsTheWindow() {
        MutableClock clock = new MutableClock(Instant.parse("2026-10-21T08:00:00Z"));
        PushCooldownService service = new PushCooldownService(config(10), clock);

        assertTrue(service.allow("metric:ph"));
        assertFalse(service.allow("metric:ph"));
        service.resetAll();
        assertTrue(service.allow("metric:ph"), "手动解除冷却后应立即放行");
    }
}
