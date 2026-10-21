package com.zhka.service;

import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 推送冷却时间。
 *
 * <p>用途：同一类告警在窗口期内只允许推送一次，防止传感器抖动、RTU 高频上报
 * 或登录爆破把推送通道打爆（推送服务一般也有频率限制，超了会被封）。
 *
 * <p>每个调用方给一个 key（例如 {@code metric:water_level}、{@code login:admin}），
 * 不同 key 各自计时、互不影响；{@link #allow(String)} 是原子的
 * 「检查 + 占位」，并发下也只会有一个线程拿到推送资格。
 *
 * <p>计时保存在内存里：进程重启后冷却窗口清零（可能多推一条），
 * 这对告警场景是可接受的取舍——换成持久化反而要多一次数据库依赖。
 */
@Service
public class PushCooldownService {

    private final PushConfigService config;
    private final Clock clock;
    private final ConcurrentHashMap<String, Instant> lastAllowed = new ConcurrentHashMap<>();

    public PushCooldownService(PushConfigService config, Clock clock) {
        this.config = config;
        this.clock = clock;
    }

    /** 按管理页配置的冷却时间判断是否允许推送 */
    public boolean allow(String key) {
        return allow(key, config.cooldownMinutes());
    }

    /**
     * @param minutes 冷却分钟数；<= 0 表示不限制
     * @return true 表示本次可以推送，并且已经把时间窗口刷新为「现在」
     */
    public boolean allow(String key, int minutes) {
        if (key == null || key.isBlank()) {
            return true;
        }
        if (minutes <= 0) {
            return true;
        }
        Duration window = Duration.ofMinutes(minutes);
        Instant now = clock.instant();
        boolean[] allowed = {false};
        lastAllowed.compute(key, (ignored, last) -> {
            if (last != null && now.isBefore(last.plus(window))) {
                return last;
            }
            allowed[0] = true;
            return now;
        });
        return allowed[0];
    }

    /** 距离下次允许推送还剩多少秒；0 表示现在就可以推 */
    public long remainingSeconds(String key) {
        return remainingSeconds(key, config.cooldownMinutes());
    }

    public long remainingSeconds(String key, int minutes) {
        if (key == null || key.isBlank() || minutes <= 0) {
            return 0;
        }
        Instant last = lastAllowed.get(key);
        if (last == null) {
            return 0;
        }
        Instant next = last.plus(Duration.ofMinutes(minutes));
        long seconds = Duration.between(clock.instant(), next).getSeconds();
        return Math.max(0, seconds);
    }

    /** 当前所有 key 的剩余冷却秒数（只包含窗口内的） */
    public Map<String, Long> snapshot() {
        Map<String, Long> result = new LinkedHashMap<>();
        int minutes = config.cooldownMinutes();
        if (minutes <= 0) {
            return result;
        }
        lastAllowed.forEach((key, value) -> {
            long remaining = remainingSeconds(key, minutes);
            if (remaining > 0) {
                result.put(key, remaining);
            }
        });
        return result;
    }

    /** 解除某个 key 的冷却 */
    public void reset(String key) {
        if (key != null) {
            lastAllowed.remove(key);
        }
    }

    /** 解除全部冷却 */
    public void resetAll() {
        lastAllowed.clear();
    }
}
