package com.zhka.util;

import com.zhka.common.BusinessException;
import org.springframework.http.HttpStatus;

import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.OffsetDateTime;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;

/**
 * 时间参数解析。
 *
 * <p>前端可能送来四种形态，这里统一转成 {@link Instant}（UTC）再交给 MongoDB：
 * <ol>
 *   <li>{@code datetime-local} 的原始值，如 {@code 2026-10-21T13:14}（无时区，按平台时区解释）</li>
 *   <li>空格分隔的旧格式，如 {@code 2026-10-21 13:14:00}（历史接口在用）</li>
 *   <li>带时区的 ISO-8601，如 {@code 2026-10-21T05:14:00Z} / {@code +08:00}</li>
 *   <li>纯日期 {@code 2026-10-21}：作为开始时间取当天 00:00，作为结束时间取当天最后一毫秒</li>
 * </ol>
 * 解析失败抛 400，而不是静默按 1970 年处理——旧实现用 {@code 1970-01-01} 兜底，
 * 一旦格式写错会导出整个库，很难发现。
 */
public final class TimeParser {

    private TimeParser() {
    }

    /**
     * @param text     原始文本；空白返回 null
     * @param endOfDay 只给日期时，是否取当天 23:59:59.999（结束时间用 true）
     * @param zone     无时区文本的时区
     */
    public static Instant parse(String text, boolean endOfDay, ZoneId zone) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String value = text.trim();

        // 毫秒 / 秒级时间戳（前端某些组件会直接给数字）
        if (value.matches("\\d{13}")) {
            return Instant.ofEpochMilli(Long.parseLong(value));
        }
        if (value.matches("\\d{10}")) {
            return Instant.ofEpochSecond(Long.parseLong(value));
        }

        try {
            return OffsetDateTime.parse(value).toInstant();
        } catch (DateTimeParseException ignored) {
            // 继续尝试其它格式
        }
        try {
            return Instant.parse(value);
        } catch (DateTimeParseException ignored) {
            // 继续尝试其它格式
        }

        // "yyyy-MM-dd HH:mm[:ss]" 与 "yyyy-MM-ddTHH:mm[:ss[.SSS]]"
        String iso = value.indexOf(' ') > 0 ? value.replace(' ', 'T') : value;
        try {
            LocalDateTime local = LocalDateTime.parse(iso, DateTimeFormatter.ISO_LOCAL_DATE_TIME);
            return local.atZone(zone).toInstant();
        } catch (DateTimeParseException ignored) {
            // 继续尝试纯日期
        }

        try {
            LocalDate date = LocalDate.parse(value, DateTimeFormatter.ISO_LOCAL_DATE);
            LocalDateTime local = endOfDay
                    ? date.atTime(LocalTime.MAX)
                    : date.atStartOfDay();
            return local.atZone(zone).toInstant();
        } catch (DateTimeParseException ignored) {
            throw new BusinessException("时间格式不正确：" + text, HttpStatus.BAD_REQUEST);
        }
    }

    /** 按平台时区格式化，用于 CSV 与推送内容 */
    public static String format(Instant instant, ZoneId zone) {
        if (instant == null) {
            return "";
        }
        return DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
                .format(instant.atZone(zone));
    }
}
