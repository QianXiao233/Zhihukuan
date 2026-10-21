package com.zhka.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Clock;

/**
 * 可注入的时钟。
 *
 * <p>冷却时间、告警时间的计算都通过 {@link Clock} 取「现在」，
 * 单元测试用 {@code Clock.fixed} 就能精确验证「冷却期内不再推送」，
 * 不用 {@code Thread.sleep}。
 */
@Configuration
public class ClockConfig {

    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }
}
