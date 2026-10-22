package com.zhka.service;

import com.zhka.config.PlatformProperties;
import com.zhka.dto.Thresholds;
import com.zhka.entity.AlertEvent;
import com.zhka.entity.Metric;
import com.zhka.entity.WaterReading;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
/**
 * 平台运行数据快照：把 AI 助手可能用到的实时数据整理成一段可读文本。
 *
 * <p>每次对话把这段文本拼在用户问题前面，Dify 就能在问水位、闸门、传感器、
 * 告警时直接使用当前值，而不是只靠训练知识。数据全部来自平台自身：
 * MongoDB 最新水情、MySQL 阈值与告警、配置里的站点名。
 *
 * <p>设计原则：
 * <ul>
 *   <li>任何数据源失败都不能影响问答，失败时退化为「没有数据」的说明；</li>
 *   <li>明确告诉模型不要编造读数、引用时说明数据时间、与问题无关时忽略；</li>
 *   <li>文本尽量短（约 200 字），避免每轮对话消耗过多 token。</li>
 * </ul>
 */
@Service
public class PlatformRuntimeService {

    private static final Logger log = LoggerFactory.getLogger(PlatformRuntimeService.class);

    private static final DateTimeFormatter DATE_TIME = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final DateTimeFormatter TIME = DateTimeFormatter.ofPattern("HH:mm:ss");

    private final WaterReadingService readings;
    private final ThresholdProvider thresholds;
    private final AlertService alerts;
    private final PlatformProperties platform;

    public PlatformRuntimeService(WaterReadingService readings, ThresholdProvider thresholds,
                                  AlertService alerts, PlatformProperties platform) {
        this.readings = readings;
        this.thresholds = thresholds;
        this.alerts = alerts;
        this.platform = platform;
    }

    /**
     * 把实时数据拼在用户问题前面。
     *
     * <p>只处理有文字的问题；纯图片消息不注入，避免干扰多模态理解。
     * 任何异常都退回原问题，保证问答主链路不受影响。
     */
    public String augment(String query) {
        if (query == null || query.isBlank()) {
            return query;
        }
        try {
            return contextBlock() + "\n\n用户问题：" + query;
        } catch (Exception e) {
            log.warn("[AI] 组装平台实时数据失败，本轮按普通问答处理: {}", e.getMessage());
            return query;
        }
    }

    /** 供 AI 使用的纯文本快照 */
    public String contextBlock() {
        Instant now = Instant.now();
        WaterReading reading = latestReading();
        Thresholds current = currentThresholds();

        StringBuilder text = new StringBuilder("【平台实时数据】\n");
        text.append("站点：").append(platform.getStationName()).append('\n');
        text.append("生成时间：").append(DATE_TIME.format(now.atZone(platform.zone()))).append('\n');

        if (reading == null) {
            text.append("当前没有收到 RTU 水情数据（MQTT 未上报，或水情库暂时不可用）。\n");
        } else {
            long ageSeconds = Math.max(0L, Duration.between(reading.getTime(), now).getSeconds());
            text.append("数据时间：").append(formatInstant(reading.getTime()))
                    .append("（").append(ageText(ageSeconds)).append("）\n");
            if (ageSeconds > 60) {
                text.append("注意：数据已超过 60 秒未更新，RTU 可能离线。\n");
            }
            text.append(metricLine(Metric.LEVEL, reading.getLevel(), current)).append('\n');
            text.append(metricLine(Metric.TEMPERATURE, reading.getTemperature(), current)).append('\n');
            text.append(metricLine(Metric.PH, reading.getPh(), current)).append('\n');
            text.append(metricLine(Metric.ORP, reading.getOrp(), current)).append('\n');
            text.append("闸门：").append(gateText(reading)).append("（1=开，0=关）\n");
            text.append("最近告警：").append(alertText()).append('\n');
        }

        text.append("使用说明：以上是平台当前实时数据，仅当用户问题涉及水情、闸门、传感器、告警或平台运行状态时使用；"
                + "引用读数时说明数据时间；不要编造上面没有的数据；与问题无关时忽略本段。"
                + "平台不会自动跳转页面：如需引导用户查看某个页面，请说“可点击下方按钮打开”，"
                + "不要声称“正在为您跳转”或“已为您跳转”。");
        return text.toString();
    }

    /** 结构化快照（调试接口 / 前端状态展示用） */
    public Map<String, Object> snapshot() {
        Instant now = Instant.now();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("station", platform.getStationName());
        data.put("generatedAt", formatInstant(now));
        WaterReading reading = latestReading();
        if (reading == null) {
            data.put("hasData", false);
            data.put("message", "当前没有收到 RTU 水情数据");
            return data;
        }
        data.put("hasData", true);
        data.put("dataTime", formatInstant(reading.getTime()));
        data.put("ageSeconds", Math.max(0L, Duration.between(reading.getTime(), now).getSeconds()));
        data.put("level", reading.getLevel());
        data.put("temperature", reading.getTemperature());
        data.put("ph", reading.getPh());
        data.put("orp", reading.getOrp());
        Map<String, String> gates = new LinkedHashMap<>();
        Integer[] relays = {reading.getRelay1(), reading.getRelay2(), reading.getRelay3(),
                reading.getRelay4(), reading.getRelay5(), reading.getRelay6()};
        for (int i = 0; i < relays.length; i++) {
            gates.put(String.valueOf(i + 1), gateState(relays[i]));
        }
        data.put("gates", gates);
        Thresholds current = currentThresholds();
        data.put("abnormalMetrics", current.violatedFields(reading));
        data.put("recentAlerts", alertsOfForSnapshot());
        return data;
    }

    private WaterReading latestReading() {
        try {
            return readings.latestOrNull();
        } catch (Exception e) {
            log.debug("[AI] 读取最新水情失败: {}", e.getMessage());
            return null;
        }
    }

    private Thresholds currentThresholds() {
        try {
            return thresholds.current();
        } catch (Exception e) {
            return Thresholds.empty();
        }
    }

    private String metricLine(Metric metric, Double value, Thresholds current) {
        Thresholds.MetricThreshold threshold = current.of(metric);
        String unit = metric.unit();
        String valueText = value == null
                ? "缺测"
                : number(value, metric.digits()) + (unit.isEmpty() ? "" : " " + unit);
        if (threshold == null || !threshold.configured()) {
            return metric.label() + "：" + valueText + "（未配置阈值）";
        }
        String state = value == null ? "缺测" : threshold.violated(value) ? threshold.direction(value) : "正常";
        return metric.label() + "：" + valueText + "（阈值 " + threshold.text() + "，" + state + "）";
    }

    private String gateText(WaterReading reading) {
        Integer[] relays = {reading.getRelay1(), reading.getRelay2(), reading.getRelay3(),
                reading.getRelay4(), reading.getRelay5(), reading.getRelay6()};
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < relays.length; i++) {
            if (i > 0) {
                text.append("、");
            }
            text.append(i + 1).append(' ').append(gateState(relays[i]));
        }
        return text.toString();
    }

    private static String gateState(Integer value) {
        if (value == null) {
            return "未知";
        }
        return value == 1 ? "开" : "关";
    }

    private String alertText() {
        List<AlertEvent> recent = alertsOf();
        if (recent.isEmpty()) {
            return "无";
        }
        StringBuilder text = new StringBuilder();
        for (int i = 0; i < recent.size() && i < 3; i++) {
            AlertEvent event = recent.get(i);
            if (i > 0) {
                text.append("；");
            }
            text.append(event.getTime() == null ? "" : TIME.format(event.getTime())).append(' ')
                    .append(event.getMetricName() == null ? event.getMetricCode() : event.getMetricName())
                    .append(' ').append(event.getReadingValue() == null ? "—" : number(event.getReadingValue(), 2))
                    .append(event.getUnit() == null ? "" : event.getUnit())
                    .append(' ').append(event.getDirection() == null ? "" : event.getDirection());
        }
        return text.toString();
    }

    private List<AlertEvent> alertsOf() {
        try {
            return alerts.recent(3);
        } catch (Exception e) {
            return List.of();
        }
    }

    private List<Map<String, Object>> alertsOfForSnapshot() {
        return alertsOf().stream().map(event -> {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("metric", event.getMetricName());
            item.put("value", event.getReadingValue());
            item.put("unit", event.getUnit());
            item.put("direction", event.getDirection());
            item.put("time", event.getTime() == null ? null : TIME.format(event.getTime()));
            item.put("status", event.getStatus());
            return item;
        }).toList();
    }

    private String formatInstant(Instant instant) {
        return DATE_TIME.format(instant.atZone(platform.zone()));
    }

    private static String number(double value, int digits) {
        return String.format(Locale.ROOT, "%." + digits + "f", value);
    }

    private static String ageText(long seconds) {
        if (seconds < 60) {
            return seconds + " 秒前";
        }
        if (seconds < 3600) {
            return (seconds / 60) + " 分钟前";
        }
        if (seconds < 86_400) {
            return (seconds / 3600) + " 小时前";
        }
        return (seconds / 86_400) + " 天前";
    }
}
