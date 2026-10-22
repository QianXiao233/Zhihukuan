package com.zhka.service;

import java.util.ArrayList;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 总线主题匹配与校验。
 *
 * <p>主题形如 {@code alarm.dam1.level}，订阅/发布权限支持两种通配：
 * <ul>
 *   <li>{@code *} 匹配一个层级：{@code alarm.*} 能匹配 {@code alarm.dam1}，不匹配 {@code alarm.dam1.level}</li>
 *   <li>{@code #} 匹配任意后缀：{@code alarm.#} 匹配 {@code alarm.dam1.level}</li>
 * </ul>
 * 发布时主题必须是具体的（不允许带通配符）。
 */
public final class BusTopicMatcher {

    /** 具体主题：字母数字下划线短横线，按点分层 */
    private static final Pattern TOPIC = Pattern.compile("^[A-Za-z0-9_-]+(\\.[A-Za-z0-9_-]+)*$");

    private BusTopicMatcher() {
    }

    public static boolean isValidTopic(String topic) {
        return topic != null && TOPIC.matcher(topic).matches();
    }

    /** 订阅模式串是否覆盖全部主题（只要有一个 # 就是） */
    public static boolean coversAll(String patternsCsv) {
        for (String pattern : split(patternsCsv)) {
            if ("#".equals(pattern)) {
                return true;
            }
        }
        return false;
    }

    /** 主题是否匹配逗号分隔的任一模式 */
    public static boolean matchesAny(String topic, String patternsCsv) {
        if (topic == null) {
            return false;
        }
        for (String pattern : split(patternsCsv)) {
            if (Pattern.matches(patternToRegex(pattern), topic)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 把模式串编译成一个 Mongo 可用的正则（不含首尾斜杠）。
     *
     * @return 覆盖全部主题时返回 null（调用方应跳过主题过滤）
     */
    public static String toRegex(String patternsCsv) {
        if (coversAll(patternsCsv)) {
            return null;
        }
        List<String> parts = new ArrayList<>();
        for (String pattern : split(patternsCsv)) {
            parts.add(patternToRegex(pattern));
        }
        if (parts.isEmpty()) {
            // 没有任何模式：给一个不可能匹配的正则，避免越权拿到全部消息
            return "(?!)";
        }
        return "^(?:" + String.join("|", parts) + ")$";
    }

    private static List<String> split(String patternsCsv) {
        List<String> patterns = new ArrayList<>();
        if (patternsCsv == null) {
            return patterns;
        }
        for (String raw : patternsCsv.split(",")) {
            String pattern = raw.trim();
            if (!pattern.isEmpty()) {
                patterns.add(pattern);
            }
        }
        return patterns;
    }

    private static String patternToRegex(String pattern) {
        StringBuilder regex = new StringBuilder();
        int index = 0;
        while (index < pattern.length()) {
            char current = pattern.charAt(index);
            if (current == '#') {
                regex.append(".*");
                index++;
            } else if (current == '*') {
                regex.append("[^.]+");
                index++;
            } else {
                int end = index;
                while (end < pattern.length() && pattern.charAt(end) != '#' && pattern.charAt(end) != '*') {
                    end++;
                }
                regex.append(Pattern.quote(pattern.substring(index, end)));
                index = end;
            }
        }
        return regex.toString();
    }
}
