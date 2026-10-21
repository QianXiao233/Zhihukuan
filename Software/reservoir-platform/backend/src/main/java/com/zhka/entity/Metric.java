package com.zhka.entity;

/**
 * 水情监测指标。
 *
 * <p>把「数据库里的参数编码（dam_system_param.param_code）」「MongoDB 文档字段名」
 * 「页面展示名 / 单位」收敛到一处：阈值、统计、告警、CSV 导出都按同一个枚举遍历，
 * 新增一个指标只需要在枚举里加一行，再在 {@link WaterReading} 里补字段。
 */
public enum Metric {

    /** 水位（m） */
    LEVEL("water_level", "level", "水位", "m", 2),
    /** 液温（℃） */
    TEMPERATURE("temperature", "temperature", "液温", "℃", 1),
    /** pH 值（无量纲） */
    PH("ph", "ph", "pH", "", 2),
    /** 氧化还原电位（mV） */
    ORP("orp", "orp", "ORP", "mV", 0);

    private final String code;
    private final String field;
    private final String label;
    private final String unit;
    private final int digits;

    Metric(String code, String field, String label, String unit, int digits) {
        this.code = code;
        this.field = field;
        this.label = label;
        this.unit = unit;
        this.digits = digits;
    }

    /** 数据库参数编码，与 dam_system_param.param_code 对应 */
    public String code() {
        return code;
    }

    /** MongoDB / DTO 中的字段名 */
    public String field() {
        return field;
    }

    /** 页面展示名 */
    public String label() {
        return label;
    }

    public String unit() {
        return unit;
    }

    /** 展示保留的小数位数 */
    public int digits() {
        return digits;
    }

    /** 读取一条记录里的指标值；缺测返回 null */
    public Double read(WaterReading reading) {
        if (reading == null) {
            return null;
        }
        return switch (this) {
            case LEVEL -> reading.getLevel();
            case TEMPERATURE -> reading.getTemperature();
            case PH -> reading.getPh();
            case ORP -> reading.getOrp();
        };
    }

    /**
     * 按参数编码解析指标，兼容历史数据的别名（level / temp）。
     *
     * @return 无法识别时返回 null（例如用户自定义的其它参数）
     */
    public static Metric ofCode(String code) {
        if (code == null) {
            return null;
        }
        String normalized = code.trim().toLowerCase();
        return switch (normalized) {
            case "water_level", "level" -> LEVEL;
            case "temperature", "temp" -> TEMPERATURE;
            case "ph" -> PH;
            case "orp" -> ORP;
            default -> null;
        };
    }
}
