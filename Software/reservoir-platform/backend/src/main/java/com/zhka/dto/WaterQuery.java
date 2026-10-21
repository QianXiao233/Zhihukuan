package com.zhka.dto;

import com.zhka.common.BusinessException;
import com.zhka.util.TimeParser;
import org.springframework.http.HttpStatus;

import java.time.Instant;
import java.time.ZoneId;
import java.util.Map;

/**
 * 水情记录的筛选条件。
 *
 * <p>所有字段都是可选的：不传就不参与过滤。数值区间用 {@code min_*} / {@code max_*}，
 * 闸门用 {@code relay1..relay6}（1=开 / 0=关 / 空=不限），
 * {@code abnormal=true} 只看超出当前阈值的记录。
 */
public final class WaterQuery {

    /** 单页上限：再大就没必要了，导出走独立接口 */
    public static final int MAX_PAGE_SIZE = 200;

    private Instant start;
    private Instant end;

    private Double minLevel;
    private Double maxLevel;
    private Double minTemperature;
    private Double maxTemperature;
    private Double minPh;
    private Double maxPh;
    private Double minOrp;
    private Double maxOrp;

    private Integer relay1;
    private Integer relay2;
    private Integer relay3;
    private Integer relay4;
    private Integer relay5;
    private Integer relay6;

    private boolean abnormalOnly;

    private int page = 1;
    private int size = 20;
    private boolean descending = true;

    public WaterQuery() {
    }

    /**
     * 从请求参数构建。
     *
     * @param params 前端传来的扁平参数（可能含空串）
     * @param zone   无时区时间文本的解释时区
     */
    public static WaterQuery from(Map<String, String> params, ZoneId zone) {
        WaterQuery query = new WaterQuery();
        if (params == null) {
            return query;
        }
        query.start = TimeParser.parse(params.get("start"), false, zone);
        query.end = TimeParser.parse(params.get("end"), true, zone);
        if (query.start != null && query.end != null && query.start.isAfter(query.end)) {
            throw new BusinessException("开始时间不能晚于结束时间", HttpStatus.BAD_REQUEST);
        }

        query.minLevel = decimal(params.get("min_level"));
        query.maxLevel = decimal(params.get("max_level"));
        query.minTemperature = decimal(params.get("min_temperature"));
        query.maxTemperature = decimal(params.get("max_temperature"));
        query.minPh = decimal(params.get("min_ph"));
        query.maxPh = decimal(params.get("max_ph"));
        query.minOrp = decimal(params.get("min_orp"));
        query.maxOrp = decimal(params.get("max_orp"));

        query.relay1 = gate(params.get("relay1"));
        query.relay2 = gate(params.get("relay2"));
        query.relay3 = gate(params.get("relay3"));
        query.relay4 = gate(params.get("relay4"));
        query.relay5 = gate(params.get("relay5"));
        query.relay6 = gate(params.get("relay6"));

        query.abnormalOnly = truthy(params.get("abnormal"));

        query.page = Math.max(1, integer(params.get("page"), 1));
        int requestedSize = integer(params.get("size"), integer(params.get("limit"), 20));
        query.size = Math.max(1, Math.min(requestedSize, MAX_PAGE_SIZE));
        query.descending = !"asc".equalsIgnoreCase(text(params.get("sort")));
        return query;
    }

    /** 换页时只改页码，其余条件不变（导出接口复用） */
    public WaterQuery withPage(int page, int size) {
        this.page = Math.max(1, page);
        this.size = Math.max(1, Math.min(size, MAX_PAGE_SIZE));
        return this;
    }

    /**
     * 导出专用：允许超过单页上限（上限由导出接口自己控制）。
     *
     * <p>故意和 {@link #withPage} 分开，避免普通分页接口误传一个巨大的 size。
     */
    public WaterQuery forExport(int limit) {
        this.page = 1;
        this.size = Math.max(1, limit);
        return this;
    }

    public long offset() {
        return (long) (page - 1) * size;
    }

    private static String text(String value) {
        return value == null ? "" : value.trim();
    }

    private static boolean truthy(String value) {
        String normalized = text(value).toLowerCase();
        return "1".equals(normalized) || "true".equals(normalized) || "yes".equals(normalized);
    }

    private static int integer(String value, int fallback) {
        try {
            String normalized = text(value);
            return normalized.isEmpty() ? fallback : Integer.parseInt(normalized);
        } catch (NumberFormatException e) {
            return fallback;
        }
    }

    private static Double decimal(String value) {
        String normalized = text(value);
        if (normalized.isEmpty()) {
            return null;
        }
        try {
            return Double.valueOf(normalized);
        } catch (NumberFormatException e) {
            throw new BusinessException("筛选数值格式不正确：" + value, HttpStatus.BAD_REQUEST);
        }
    }

    private static Integer gate(String value) {
        String normalized = text(value);
        if (normalized.isEmpty()) {
            return null;
        }
        try {
            int parsed = Integer.parseInt(normalized);
            return parsed == 0 || parsed == 1 ? parsed : null;
        } catch (NumberFormatException e) {
            return null;
        }
    }

    public Instant getStart() {
        return start;
    }

    public Instant getEnd() {
        return end;
    }

    public Double getMinLevel() {
        return minLevel;
    }

    public Double getMaxLevel() {
        return maxLevel;
    }

    public Double getMinTemperature() {
        return minTemperature;
    }

    public Double getMaxTemperature() {
        return maxTemperature;
    }

    public Double getMinPh() {
        return minPh;
    }

    public Double getMaxPh() {
        return maxPh;
    }

    public Double getMinOrp() {
        return minOrp;
    }

    public Double getMaxOrp() {
        return maxOrp;
    }

    public Integer getRelay1() {
        return relay1;
    }

    public Integer getRelay2() {
        return relay2;
    }

    public Integer getRelay3() {
        return relay3;
    }

    public Integer getRelay4() {
        return relay4;
    }

    public Integer getRelay5() {
        return relay5;
    }

    public Integer getRelay6() {
        return relay6;
    }

    /** 按 1..6 取闸门条件，下标从 0 开始 */
    public Integer relay(int index) {
        return switch (index) {
            case 0 -> relay1;
            case 1 -> relay2;
            case 2 -> relay3;
            case 3 -> relay4;
            case 4 -> relay5;
            case 5 -> relay6;
            default -> null;
        };
    }

    public boolean isAbnormalOnly() {
        return abnormalOnly;
    }

    public int getPage() {
        return page;
    }

    public int getSize() {
        return size;
    }

    public boolean isDescending() {
        return descending;
    }
}
