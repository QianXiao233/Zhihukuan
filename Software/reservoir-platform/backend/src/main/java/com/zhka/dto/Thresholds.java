package com.zhka.dto;

import com.zhka.entity.DamSystemParam;
import com.zhka.entity.Metric;
import com.zhka.entity.WaterReading;

import java.util.EnumMap;
import java.util.List;
import java.util.Map;

/**
 * 监测阈值快照（来自 MySQL 的 {@code dam_system_param}）。
 *
 * <p>阈值在数据库里存的是字符串，可能为空、可能是非法数字；这里统一解析成
 * {@link Double}，非法或空值视为「该侧不设限」，避免一次手误把整条告警链路弄坏。
 */
public final class Thresholds {

    /**
     * 单个指标的阈值。
     *
     * @param low  下限，null 表示不设下限
     * @param high 上限，null 表示不设上限
     */
    public record MetricThreshold(Metric metric, String name, Double low, Double high) {

        public boolean configured() {
            return low != null || high != null;
        }

        /** 是否越界；缺测（null）不算越界 */
        public boolean violated(Double value) {
            if (value == null) {
                return false;
            }
            return (low != null && value < low) || (high != null && value > high);
        }

        /** 越界方向描述，用于告警文案 */
        public String direction(Double value) {
            if (value == null) {
                return "";
            }
            if (low != null && value < low) {
                return "低于下限";
            }
            if (high != null && value > high) {
                return "高于上限";
            }
            return "超出范围";
        }

        /** "6.50 ~ 8.50 pH" 这样的展示文本 */
        public String text() {
            if (!configured()) {
                return "未配置";
            }
            String unit = metric.unit();
            String range = (low == null ? "—" : trim(low)) + " ~ " + (high == null ? "—" : trim(high));
            return unit.isEmpty() ? range : range + " " + unit;
        }

        private static String trim(double value) {
            if (value == Math.rint(value)) {
                return String.valueOf((long) value);
            }
            return String.valueOf(value);
        }
    }

    private final Map<Metric, MetricThreshold> byMetric;

    private Thresholds(Map<Metric, MetricThreshold> byMetric) {
        this.byMetric = byMetric;
    }

    public static Thresholds empty() {
        return new Thresholds(new EnumMap<>(Metric.class));
    }

    /** 从参数表构建；同一个指标出现多次时以最后一条为准 */
    public static Thresholds from(List<DamSystemParam> params) {
        Map<Metric, MetricThreshold> map = new EnumMap<>(Metric.class);
        if (params != null) {
            for (DamSystemParam param : params) {
                Metric metric = Metric.ofCode(param.getParamCode());
                if (metric == null) {
                    continue;
                }
                Double low = number(param.getParamLowValue());
                Double high = number(param.getParamHighValue());
                String name = param.getParamName() == null || param.getParamName().isBlank()
                        ? metric.label()
                        : param.getParamName().trim();
                map.put(metric, new MetricThreshold(metric, name, low, high));
            }
        }
        return new Thresholds(map);
    }

    public MetricThreshold of(Metric metric) {
        return byMetric.get(metric);
    }

    public boolean anyConfigured() {
        return byMetric.values().stream().anyMatch(MetricThreshold::configured);
    }

    /** 一条记录里所有越界的指标编码，供列表标红 */
    public List<String> violatedFields(WaterReading reading) {
        return byMetric.values().stream()
                .filter(threshold -> threshold.violated(threshold.metric().read(reading)))
                .map(threshold -> threshold.metric().field())
                .toList();
    }

    private static Double number(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            return Double.valueOf(text.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }
}
