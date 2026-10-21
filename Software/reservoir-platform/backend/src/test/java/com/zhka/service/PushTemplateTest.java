package com.zhka.service;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 推送模板渲染测试（纯本地，不发任何网络请求）。
 *
 * <p>重点保证三件事：变量齐全时能渲染、漏传变量要报错、外部数据必须转义。
 */
class PushTemplateTest {

    @Test
    @DisplayName("所有模板都能用 requiredVariables() 渲染，且不残留占位符")
    void allTemplatesRender() {
        for (PushTemplate template : PushTemplate.values()) {
            Map<String, Object> variables = new HashMap<>();
            template.requiredVariables().forEach(name -> variables.put(name, "值-" + name));

            String html = template.renderHtml(variables);
            assertFalse(html.contains("{"), template + " 渲染后仍残留占位符：" + html);
            assertTrue(html.contains("</table>"), template + " 正文应包含信息表格");

            String title = template.renderTitle(variables);
            assertFalse(title.contains("<"), template + " 标题是纯文本，不应包含 HTML");
            assertFalse(title.contains("\n"), template + " 标题应压成单行");
        }
    }

    @Test
    @DisplayName("漏传变量时抛出带模板名与变量名的异常")
    void missingVariableFailsFast() {
        Map<String, Object> variables = new HashMap<>();
        variables.put("damName", "青龙水库");

        IllegalArgumentException error = assertThrows(IllegalArgumentException.class,
                () -> PushTemplate.WATER_LEVEL_ALERT.renderHtml(variables));

        assertTrue(error.getMessage().contains("缺少变量"), error.getMessage());
        assertTrue(error.getMessage().contains("WATER_LEVEL_ALERT"), error.getMessage());
    }

    @Test
    @DisplayName("外部数据中的 HTML 会被转义，不会破坏版式")
    void escapesUserSuppliedHtml() {
        Map<String, Object> variables = new HashMap<>();
        variables.put("module", "<script>alert(1)</script>");
        variables.put("errorType", "NPE & OOM");
        variables.put("message", "\"quoted\"");
        variables.put("time", "2026-10-19 19:40");

        String html = PushTemplate.SYSTEM_ERROR_ALERT.renderHtml(variables);

        assertFalse(html.contains("<script>alert(1)</script>"), "脚本标签必须被转义");
        assertTrue(html.contains("&lt;script&gt;alert(1)&lt;/script&gt;"));
        assertTrue(html.contains("NPE &amp; OOM"), "& 必须转义且不能二次转义");
        assertTrue(html.contains("&quot;quoted&quot;"));
    }

    @Test
    @DisplayName("模板声明的必需变量与实际占位符一致")
    void requiredVariablesMatchPlaceholders() {
        assertTrue(PushTemplate.WATER_LEVEL_ALERT.requiredVariables()
                .containsAll(List.of("damName", "currentLevel", "threshold", "exceeded", "unit", "status", "time")));
        assertEquals(4, PushTemplate.LOGIN_ANOMALY_ALERT.requiredVariables().size());
        assertEquals(5, PushTemplate.DEVICE_OFFLINE_ALERT.requiredVariables().size());
    }
}
