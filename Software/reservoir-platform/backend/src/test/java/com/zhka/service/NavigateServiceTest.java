package com.zhka.service;

import com.zhka.dto.NavigateCommand;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 跳转指令解析测试 —— 这是「页面自动跳转」功能的关键逻辑，
 * 必须与前端 src/router/navigate.ts 的解析行为保持一致。
 */
class NavigateServiceTest {

    private final NavigateService service = new NavigateService();

    @Test
    @DisplayName("解析 Dify 实际使用的 [[jump:target]] 标记")
    void parseJumpMark() {
        String raw = "汛限水位是水库汛期允许蓄水的上限水位。 [[jump:monitor]]";

        NavigateService.Parsed parsed = service.parse(raw);

        assertEquals("汛限水位是水库汛期允许蓄水的上限水位。", parsed.text());
        assertEquals("monitor", parsed.command().target());
    }

    @Test
    @DisplayName("解析带原因的 [[jump:target|原因]] 标记")
    void parseJumpMarkWithReason() {
        NavigateService.Parsed parsed = service.parse("为您打开页面 [[jump:flood|正在进入防汛调度]]");

        assertEquals("为您打开页面", parsed.text());
        assertEquals("flood", parsed.command().target());
        assertEquals("正在进入防汛调度", parsed.command().reason());
    }

    @Test
    @DisplayName("无法识别的 jump 标记也要从正文剔除")
    void unknownJumpMarkIsStripped() {
        NavigateService.Parsed parsed = service.parse("正文内容 [[jump:not_a_page]]");

        assertEquals("正文内容", parsed.text());
        assertNull(parsed.command());
    }

    @Test
    @DisplayName("剥离已闭合的思维链")
    void stripClosedThink() {
        String raw = "<think>\n内部推理过程，不应展示。\n</think>这是给用户的回答。";

        assertEquals("这是给用户的回答。", service.stripThink(raw));
    }

    @Test
    @DisplayName("剥离未闭合的思维链（流式输出中途）")
    void stripOpenThink() {
        String raw = "<think>\n还在思考中，尚未结束";

        assertEquals("", service.stripThink(raw));
    }

    @Test
    @DisplayName("思维链中的 jump 标记不触发跳转")
    void jumpInsideThinkIsIgnored() {
        String raw = "<think>我需要 [[jump:monitor]] 吗？</think>正式回答内容。";

        NavigateService.Parsed parsed = service.parse(raw);

        assertEquals("正式回答内容。", parsed.text());
        assertNull(parsed.command());
    }

    @Test
    @DisplayName("真实 Dify 回答的端到端解析")
    void parseRealDifyReply() {
        String raw = "<think>\n用户问汛限水位，属于水位预警相关。\n</think>"
                + "汛限水位是指水库在汛期为兼顾防洪安全与兴利蓄水而设定的允许最高蓄水位。 "
                + "[[jump:monitor]]";

        NavigateService.Parsed parsed = service.parse(raw);

        assertTrue(parsed.text().startsWith("汛限水位是指水库在汛期"));
        assertTrue(!parsed.text().contains("<think>"));
        assertTrue(!parsed.text().contains("[[jump"));
        assertEquals("monitor", parsed.command().target());
    }

    @Test
    @DisplayName("解析 Markdown 代码块形式的跳转指令")
    void parseCodeBlock() {
        String raw = "好的，为您打开监测页面。\n"
                + "```navigate\n"
                + "{\"action\":\"navigate\",\"target\":\"monitor\",\"reason\":\"为您打开水库监测总览\"}\n"
                + "```";

        NavigateService.Parsed parsed = service.parse(raw);

        assertEquals("好的，为您打开监测页面。", parsed.text());
        assertEquals("monitor", parsed.command().target());
        assertEquals("为您打开水库监测总览", parsed.command().reason());
        assertEquals("navigate", parsed.command().action());
    }

    @Test
    @DisplayName("解析 <navigate /> 标签形式")
    void parseTag() {
        String raw = "正在跳转 <navigate target=\"flood\" reason=\"打开防汛调度\" /> 请稍候";

        NavigateService.Parsed parsed = service.parse(raw);

        assertEquals("正在跳转  请稍候", parsed.text());
        assertEquals("flood", parsed.command().target());
        assertEquals("打开防汛调度", parsed.command().reason());
    }

    @Test
    @DisplayName("中文页面名可被识别")
    void parseChineseAlias() {
        NavigateCommand cmd = service.parse("```navigate\n{\"target\":\"巡检台账\"}\n```").command();
        assertEquals("inspection", cmd.target());
    }

    @Test
    @DisplayName("无指令时返回原文且 command 为空")
    void parseWithoutCommand() {
        NavigateService.Parsed parsed = service.parse("这是一段普通回答，不含任何跳转指令。");

        assertEquals("这是一段普通回答，不含任何跳转指令。", parsed.text());
        assertNull(parsed.command());
    }

    @Test
    @DisplayName("非法页面标识不产生跳转")
    void parseInvalidTarget() {
        NavigateCommand cmd = service.parse("```navigate\n{\"target\":\"unknown_page\"}\n```").command();
        assertNull(cmd);
    }

    @Test
    @DisplayName("normalize 支持大小写与部分匹配")
    void normalize() {
        assertEquals("home", service.normalize("HOME"));
        assertEquals("monitor", service.normalize("水库监测"));
        assertEquals("ecology", service.normalize("生态管护页面"));
        assertNull(service.normalize("随便什么"));
    }

    @Test
    @DisplayName("流式累积文本可提前探测到指令")
    void detectIncremental() {
        String partial = "稍等\n```navigate\n{\"target\":\"policy\"}\n```";
        assertTrue(service.detect(partial) != null);
        assertEquals("policy", service.detect(partial).target());
    }

    @Test
    @DisplayName("流式中途未闭合的指令不触发跳转")
    void detectIncomplete() {
        assertNull(service.detect("稍等\n```navigate\n{\"target\":\"pol"));
    }
}
