package com.zhka.service;

import java.util.LinkedHashSet;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 推送消息模板（HTML）。
 *
 * <p>每个枚举值自带「标题模板」和「正文模板」，正文用 {@code {变量名}} 占位；
 * 渲染时把调用方传入的值做 HTML 转义后填入，因此外部数据（库名、用户名、异常信息等）
 * 里即使含有 {@code <} 也不会破坏版式。
 *
 * <p>用法见 {@link PushService#push(String, PushTemplate, Map)}：
 * <pre>{@code
 * pushService.pushAsync(token, PushTemplate.WATER_LEVEL_ALERT, Map.of(
 *         "damName", "青龙水库",
 *         "currentLevel", "129.20",
 *         "threshold", "129.00",
 *         "exceeded", "0.20",
 *         "unit", "m",
 *         "status", "超汛限",
 *         "time", "2026-10-19 19:40"));
 * }</pre>
 *
 * <p>新增模板：加一个枚举值，正文里用 {@code {变量名}} 占位即可，
 * 调用方漏传变量时 {@link #renderHtml(Map)} 会抛出带变量名的异常，
 * 不会把 {@code {xxx}} 原样发出去。
 */
public enum PushTemplate {

    /** 水位异常告警 */
    WATER_LEVEL_ALERT(
            "【水位告警】{damName} 水位异常",
            "水位异常告警",
            "#d93025",
            "#fdf3f2",
            """
            <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">
              <tr>
                <td style="padding:6px 8px;color:#6b7280;width:100px;border-bottom:1px solid #eef0f2">水库名称</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;font-weight:600">{damName}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">当前水位</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2"><span style="color:#d93025;font-weight:600">{currentLevel}</span> {unit}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">汛限水位</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{threshold} {unit}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">超出幅度</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{exceeded} {unit}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">告警级别</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;color:#d93025;font-weight:600">{status}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">发生时间</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{time}</td>
              </tr>
            </table>
            <div style="margin-top:12px;padding:10px 12px;background:#f6f8fa;border-radius:6px;font-size:12px;color:#57606a">
              建议：立即核查水位计读数与闸门状态，按防汛调度预案处置。
            </div>
            """),

    /** 用户登录异常告警 */
    LOGIN_ANOMALY_ALERT(
            "【登录告警】{username} 登录异常",
            "用户登录异常告警",
            "#b45309",
            "#fffbeb",
            """
            <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">
              <tr>
                <td style="padding:6px 8px;color:#6b7280;width:100px;border-bottom:1px solid #eef0f2">账号</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;font-weight:600">{username}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">异常原因</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;color:#b45309;font-weight:600">{reason}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">来源 IP</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{ip}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">发生时间</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{time}</td>
              </tr>
            </table>
            <div style="margin-top:12px;padding:10px 12px;background:#fffbeb;border-radius:6px;font-size:12px;color:#92400e">
              建议：核实是否为本人操作；若为暴力尝试，请及时修改口令并限制来源 IP。
            </div>
            """),

    /**
     * 监测指标超出阈值告警（水位 / 液温 / pH / ORP 通用）。
     *
     * <p>由 {@code ThresholdMonitorService} 在 MQTT 读数越界时触发；
     * 每个指标各自独立冷却，避免读数在阈值附近抖动时连续轰炸。
     */
    SENSOR_THRESHOLD_ALERT(
            "【监测告警】{station} {metricName} 超出阈值",
            "监测指标超出阈值",
            "#d93025",
            "#fdf3f2",
            """
            <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">
              <tr>
                <td style="padding:6px 8px;color:#6b7280;width:100px;border-bottom:1px solid #eef0f2">监测站点</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;font-weight:600">{station}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">监测指标</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;font-weight:600">{metricName}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">当前读数</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2"><span style="color:#d93025;font-weight:600">{currentValue}</span> {unit}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">阈值范围</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{threshold}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">越界方向</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;color:#d93025;font-weight:600">{direction}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">发生时间</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{time}</td>
              </tr>
            </table>
            <div style="margin-top:12px;padding:10px 12px;background:#f6f8fa;border-radius:6px;font-size:12px;color:#57606a">
              建议：核对传感器读数与闸门状态；若持续越界，请按调度预案处置。同一指标在冷却时间内不会重复推送。
            </div>
            """),

    /** 设备离线告警 */
    DEVICE_OFFLINE_ALERT(
            "【设备告警】{deviceName} 已离线",
            "设备离线告警",
            "#b45309",
            "#fffbeb",
            """
            <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">
              <tr>
                <td style="padding:6px 8px;color:#6b7280;width:100px;border-bottom:1px solid #eef0f2">设备名称</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;font-weight:600">{deviceName}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">设备编号</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{deviceCode}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">所属水库</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{damName}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">最后上报</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{lastSeen}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">告警时间</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{time}</td>
              </tr>
            </table>
            <div style="margin-top:12px;padding:10px 12px;background:#fffbeb;border-radius:6px;font-size:12px;color:#92400e">
              建议：检查设备供电与网络链路，必要时安排现场巡检。
            </div>
            """),

    /** 系统异常告警 */
    SYSTEM_ERROR_ALERT(
            "【系统告警】{module} 异常",
            "系统异常告警",
            "#d93025",
            "#fdf3f2",
            """
            <table style="width:100%;border-collapse:collapse;font-size:13px;margin-top:12px">
              <tr>
                <td style="padding:6px 8px;color:#6b7280;width:100px;border-bottom:1px solid #eef0f2">所属模块</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;font-weight:600">{module}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">异常类型</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;color:#d93025;font-weight:600">{errorType}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">异常信息</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2;word-break:break-all">{message}</td>
              </tr>
              <tr>
                <td style="padding:6px 8px;color:#6b7280;border-bottom:1px solid #eef0f2">发生时间</td>
                <td style="padding:6px 8px;border-bottom:1px solid #eef0f2">{time}</td>
              </tr>
            </table>
            <div style="margin-top:12px;padding:10px 12px;background:#f6f8fa;border-radius:6px;font-size:12px;color:#57606a">
              建议：结合服务端日志定位堆栈，若持续触发请检查依赖服务与数据库连接。
            </div>
            """);

    private static final Pattern PLACEHOLDER = Pattern.compile("\\{([A-Za-z][A-Za-z0-9_]*)}");

    /** 标题模板（纯文本，变量不做 HTML 转义） */
    private final String titleTemplate;
    /** 卡片抬头文案 */
    private final String headline;
    /** 抬头主色 */
    private final String accentColor;
    /** 抬头浅色背景 */
    private final String headerBackground;
    /** 正文片段（表格 + 建议），变量做 HTML 转义 */
    private final String bodyTemplate;

    PushTemplate(String titleTemplate, String headline, String accentColor,
                 String headerBackground, String bodyTemplate) {
        this.titleTemplate = titleTemplate;
        this.headline = headline;
        this.accentColor = accentColor;
        this.headerBackground = headerBackground;
        this.bodyTemplate = bodyTemplate;
    }

    /** 渲染标题（纯文本）；缺少变量时抛 {@link IllegalArgumentException} */
    public String renderTitle(Map<String, Object> variables) {
        return render(titleTemplate, variables).replaceAll("\\s+", " ").trim();
    }

    /** 渲染完整 HTML 正文；缺少变量时抛 {@link IllegalArgumentException} */
    public String renderHtml(Map<String, Object> variables) {
        String header = """
                <div style="border-left:4px solid %s;background:%s;padding:10px 14px">
                  <div style="font-size:15px;font-weight:600;color:%s">%s</div>
                </div>
                """.formatted(accentColor, headerBackground, accentColor, headline);

        String footer = """
                <div style="margin-top:12px;font-size:12px;color:#9ca3af">本消息由 dam-ai-server 自动推送，请勿直接回复。</div>
                """;

        return """
                <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'PingFang SC','Microsoft YaHei',Arial,sans-serif;font-size:14px;color:#1f2328;line-height:1.6;max-width:640px">
                %s%s%s</div>
                """.formatted(header, render(bodyTemplate, variables), footer);
    }

    /** 本模板需要的全部变量名，便于调用方自检或在文档里展示 */
    public Set<String> requiredVariables() {
        Set<String> names = new LinkedHashSet<>();
        Matcher matcher = PLACEHOLDER.matcher(titleTemplate + bodyTemplate);
        while (matcher.find()) {
            names.add(matcher.group(1));
        }
        return names;
    }

    private String render(String template, Map<String, Object> variables) {
        String result = template;
        if (variables != null) {
            for (Map.Entry<String, Object> entry : variables.entrySet()) {
                Object value = entry.getValue();
                result = result.replace("{" + entry.getKey() + "}",
                        escapeHtml(value == null ? "" : String.valueOf(value)));
            }
        }

        // 变量漏传时不要发出带 {xxx} 的残缺消息
        Matcher missing = PLACEHOLDER.matcher(result);
        if (missing.find()) {
            throw new IllegalArgumentException("推送模板 " + name() + " 缺少变量: " + missing.group(1)
                    + "，需要: " + requiredVariables());
        }
        return result;
    }

    /** HTML 转义：& 必须先替换，否则会产生 &amp;lt; 之类的二次转义 */
    private static String escapeHtml(String value) {
        return value.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\"", "&quot;")
                .replace("'", "&#39;");
    }
}
