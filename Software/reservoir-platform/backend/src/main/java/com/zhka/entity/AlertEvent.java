package com.zhka.entity;

import java.time.LocalDateTime;

/**
 * 阈值告警记录，对应 MySQL 表 {@code alert_event}。
 *
 * <p>告警属于平台运行数据，和登录、台账、消息一样留在 MySQL；
 * MongoDB 只存水情读数（{@link WaterReading}）。
 *
 * <p>时间按平台时区存成 {@link LocalDateTime}，与 {@code message}、{@code platform_audit}
 * 等表的 {@code create_time} 保持一致，DBA 直接查表看到的就是本地时间。
 */
public class AlertEvent {

    /** 推送状态：已入队 */
    public static final String STATUS_QUEUED = "queued";
    /** 推送成功 */
    public static final String STATUS_SENT = "sent";
    /** 推送失败 */
    public static final String STATUS_FAILED = "failed";
    /** 推送开关关闭，未发送 */
    public static final String STATUS_SKIPPED = "skipped";
    /** 未配置 token，未发送 */
    public static final String STATUS_NO_TOKEN = "no-token";

    private Long id;
    /** 指标编码，见 {@link Metric#code()} */
    private String metricCode;
    /** 指标中文名 */
    private String metricName;
    /** 触发时的读数 */
    private Double readingValue;
    private Double lowThreshold;
    private Double highThreshold;
    private String unit;
    /** 越界方向：高于上限 / 低于下限 */
    private String direction;
    /** 见 STATUS_* 常量 */
    private String status;
    /** 是否推送成功 */
    private boolean pushed;
    /** 推送返回摘要或失败原因 */
    private String message;
    /** 告警发生时间（平台时区） */
    private LocalDateTime time;

    public AlertEvent() {
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public String getMetricCode() {
        return metricCode;
    }

    public void setMetricCode(String metricCode) {
        this.metricCode = metricCode;
    }

    public String getMetricName() {
        return metricName;
    }

    public void setMetricName(String metricName) {
        this.metricName = metricName;
    }

    public Double getReadingValue() {
        return readingValue;
    }

    public void setReadingValue(Double readingValue) {
        this.readingValue = readingValue;
    }

    public Double getLowThreshold() {
        return lowThreshold;
    }

    public void setLowThreshold(Double lowThreshold) {
        this.lowThreshold = lowThreshold;
    }

    public Double getHighThreshold() {
        return highThreshold;
    }

    public void setHighThreshold(Double highThreshold) {
        this.highThreshold = highThreshold;
    }

    public String getUnit() {
        return unit;
    }

    public void setUnit(String unit) {
        this.unit = unit;
    }

    public String getDirection() {
        return direction;
    }

    public void setDirection(String direction) {
        this.direction = direction;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public boolean isPushed() {
        return pushed;
    }

    public void setPushed(boolean pushed) {
        this.pushed = pushed;
    }

    public String getMessage() {
        return message;
    }

    public void setMessage(String message) {
        this.message = message;
    }

    public LocalDateTime getTime() {
        return time;
    }

    public void setTime(LocalDateTime time) {
        this.time = time;
    }
}
