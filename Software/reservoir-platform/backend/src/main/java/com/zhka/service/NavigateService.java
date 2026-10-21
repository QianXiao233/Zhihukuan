package com.zhka.service;

import com.zhka.dto.NavigateCommand;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 解析 Dify 回答中的页面跳转指令，并清洗正文。
 *
 * <p>支持与前端 {@code reservoir-platform/frontend/src/router/navigate.js} 一致的四种写法：
 * <ol>
 *   <li>{@code [[jump:monitor]]} / {@code [[jump:monitor|为您打开监测总览]]}（Dify 实际使用的行内标记）</li>
 *   <li>{@code ```navigate {"target":"monitor"} ```}</li>
 *   <li>{@code <navigate target="monitor" />}</li>
 *   <li>{@code [[jump]]}（无 target，仅用于剔除标记）</li>
 * </ol>
 * 另外负责剥离模型泄漏的思维链 {@code <think>...</think>}。
 */
@Service
public class NavigateService {

    /** ```navigate ... ``` / ```json:nav ... ``` */
    private static final Pattern CODE_BLOCK =
            Pattern.compile("```(?:navigate|json:nav|nav)\\s*([\\s\\S]*?)```", Pattern.CASE_INSENSITIVE);

    /** <navigate ... /> */
    private static final Pattern TAG = Pattern.compile("<navigate\\b([^>]*)/?>", Pattern.CASE_INSENSITIVE);

    private static final Pattern ATTR =
            Pattern.compile("(target|reason|params)\\s*=\\s*[\"']([^\"']*)[\"']", Pattern.CASE_INSENSITIVE);

    /** ① [[jump:target]] 或 [[jump:target|原因]] */
    private static final Pattern JUMP_MARK =
            Pattern.compile("\\[\\[\\s*jump\\s*:\\s*([^\\]|]+?)\\s*(?:\\|\\s*([^\\]]+?)\\s*)?\\]\\]",
                    Pattern.CASE_INSENSITIVE);

    /** ④ 无 target 的裸标记 [[jump]] */
    private static final Pattern BARE_JUMP =
            Pattern.compile("\\[\\[\\s*jump\\s*\\]\\]", Pattern.CASE_INSENSITIVE);

    /** 任意 jump 标记（含无法识别的 target），用于从正文中剔除 */
    private static final Pattern ANY_JUMP =
            Pattern.compile("\\[\\[\\s*jump\\s*:?[^\\]]*\\]\\]", Pattern.CASE_INSENSITIVE);

    /** 已闭合的思维链（含跨行） */
    private static final Pattern THINK_BLOCK =
            Pattern.compile("<think\\b[^>]*>[\\s\\S]*?</think>", Pattern.CASE_INSENSITIVE);

    /** 未闭合的思维链：流式输出中途 <think> 还没结束 */
    private static final Pattern OPEN_THINK =
            Pattern.compile("<think\\b[^>]*>[\\s\\S]*$", Pattern.CASE_INSENSITIVE);

    /** 合法页面标识 */
    private static final Map<String, String> TARGETS = Map.of(
            "home", "home",
            "monitor", "monitor",
            "inspection", "inspection",
            "policy", "policy",
            "flood", "flood",
            "ecology", "ecology");

    /** 中文别名 → 页面标识 */
    private static final Map<String, String> ALIASES = new LinkedHashMap<>();

    static {
        ALIASES.put("首页", "home");
        ALIASES.put("主页", "home");
        ALIASES.put("水库监测", "monitor");
        ALIASES.put("监测总览", "monitor");
        ALIASES.put("监测", "monitor");
        ALIASES.put("巡检", "inspection");
        ALIASES.put("巡查", "inspection");
        ALIASES.put("巡检台账", "inspection");
        ALIASES.put("政策", "policy");
        ALIASES.put("法规", "policy");
        ALIASES.put("政策文档", "policy");
        ALIASES.put("防汛", "flood");
        ALIASES.put("调度", "flood");
        ALIASES.put("泄洪", "flood");
        ALIASES.put("生态", "ecology");
        ALIASES.put("放流", "ecology");
    }

    /** 解析结果：清洗后的正文 + 跳转指令 */
    public record Parsed(String text, NavigateCommand command) {
    }

    /**
     * 剥离思维链内容。
     *
     * <p>流式渲染时 {@code <think>} 常尚未闭合，此时应把已出现的思考内容整段丢弃，
     * 否则用户会看到模型的内心独白。
     */
    public String stripThink(String raw) {
        if (raw == null || raw.isEmpty()) {
            return "";
        }
        return OPEN_THINK.matcher(THINK_BLOCK.matcher(raw).replaceAll("")).replaceAll("");
    }

    /**
     * 从展示文本中剔除跳转标记，并缓冲「尚未闭合的标记」。
     *
     * <p>SSE 增量会让 {@code [[jump:monitor]]} 被切成 "[[jump:"、"monitor"、"]]" 多块，
     * 逐块正则替换命不中，所以末尾未闭合的 "[[" 片段要留到下一块再拼接。
     */
    public String stripJumpMarks(String text) {
        if (text == null || text.isEmpty()) {
            return "";
        }
        String cleaned = ANY_JUMP.matcher(text).replaceAll("");
        cleaned = BARE_JUMP.matcher(cleaned).replaceAll("");

        int open = cleaned.lastIndexOf("[[");
        if (open >= 0 && cleaned.indexOf("]]", open) < 0) {
            cleaned = cleaned.substring(0, open);
        }
        return cleaned;
    }

    /** 从完整回答里提取跳转指令，并清洗正文 */
    public Parsed parse(String raw) {
        if (raw == null || raw.isEmpty()) {
            return new Parsed("", null);
        }

        String text = stripThink(raw);
        NavigateCommand command = null;

        // ① [[jump:target]] / [[jump:target|原因]] —— Dify 实际使用的格式
        Matcher jumpMatcher = JUMP_MARK.matcher(text);
        if (jumpMatcher.find()) {
            String target = normalize(jumpMatcher.group(1));
            if (target != null) {
                String reason = jumpMatcher.group(2);
                command = new NavigateCommand("navigate", target, null, reason == null ? null : reason.trim());
            }
        }
        // 无论是否识别成功，都要把标记从正文里清掉
        text = BARE_JUMP.matcher(JUMP_MARK.matcher(text).replaceAll("")).replaceAll("");

        // ② JSON 代码块
        if (command == null) {
            Matcher blockMatcher = CODE_BLOCK.matcher(text);
            if (blockMatcher.find()) {
                String json = blockMatcher.group(1).trim();
                String target = normalize(extractJsonField(json, "target|page|route"));
                if (target != null) {
                    command = new NavigateCommand("navigate", target, null, extractJsonField(json, "reason"));
                }
                text = text.replace(blockMatcher.group(0), "");
            }
        }

        // ③ <navigate ... />
        if (command == null) {
            Matcher tagMatcher = TAG.matcher(text);
            if (tagMatcher.find()) {
                String target = null;
                String reason = null;
                Matcher attrMatcher = ATTR.matcher(tagMatcher.group(1));
                while (attrMatcher.find()) {
                    String name = attrMatcher.group(1).toLowerCase();
                    String value = attrMatcher.group(2);
                    if ("target".equals(name)) {
                        target = normalize(value);
                    } else if ("reason".equals(name)) {
                        reason = value;
                    }
                }
                if (target != null) {
                    command = new NavigateCommand("navigate", target, null, reason);
                }
                text = text.replace(tagMatcher.group(0), "");
            }
        }

        return new Parsed(text.trim(), command);
    }

    /**
     * 从流式累积的正文里做「提前侦察」：一旦发现完整指令就返回，
     * 供后端尽早下发 navigate 事件。
     */
    public NavigateCommand detect(String raw) {
        return parse(raw).command();
    }

    /** 归一化页面标识：支持英文标识、中文名与部分匹配 */
    public String normalize(String raw) {
        if (raw == null) {
            return null;
        }
        String key = raw.trim();
        if (key.isEmpty()) {
            return null;
        }

        String lower = key.toLowerCase();
        if (TARGETS.containsKey(lower)) {
            return TARGETS.get(lower);
        }
        if (ALIASES.containsKey(key)) {
            return ALIASES.get(key);
        }
        for (Map.Entry<String, String> alias : ALIASES.entrySet()) {
            if (key.contains(alias.getKey())) {
                return alias.getValue();
            }
        }
        return null;
    }

    /**
     * 极轻量的字段抽取，避免为一行 JSON 引入完整解析失败的风险。
     *
     * @param alternatives 用 {@code |} 分隔的候选字段名，如 {@code "target|page|route"}
     */
    private String extractJsonField(String json, String alternatives) {
        Matcher matcher = Pattern.compile("\"(?:" + alternatives + ")\"\\s*:\\s*\"([^\"]+)\"").matcher(json);
        return matcher.find() ? matcher.group(1) : null;
    }
}
