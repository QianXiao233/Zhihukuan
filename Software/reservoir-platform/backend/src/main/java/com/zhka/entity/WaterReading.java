package com.zhka.entity;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;

/**
 * 水情采集记录（MongoDB 文档），集合 {@code water_readings}。
 *
 * <p>字段与原来的 MySQL 表 {@code water_log} 保持一一对应，只是：
 * <ul>
 *   <li>主键由自增 BIGINT 换成 ObjectId（{@code id} 在 JSON 里是字符串，前端直接用）；</li>
 *   <li>时间由 DATETIME 换成 {@link Instant}（UTC 存储，展示时按平台时区格式化）；</li>
 *   <li>数值用包装类型，缺测时是 {@code null} 而不是 0，统计和阈值判断不会把缺测当成 0；</li>
 *   <li>新增 {@code source}（mqtt / mysql-migration）与 {@code legacyId}，
 *       迁移旧数据时用它做幂等，不会重复导入。</li>
 * </ul>
 *
 * <p>闸门状态沿用 1=开 / 0=关 的约定，对应 RTU 上报报文里的 {@code relay[0..5]}。
 */
@Document(collection = WaterReading.COLLECTION)
public class WaterReading {

    public static final String COLLECTION = "water_readings";

    /** RTU 实时上报 */
    public static final String SOURCE_MQTT = "mqtt";
    /** 从旧 MySQL 表迁移过来 */
    public static final String SOURCE_MIGRATION = "mysql-migration";

    @Id
    private String id;

    /** 采集时间（UTC） */
    private Instant time;

    /** 水位（m） */
    private Double level;
    /** 液温（℃） */
    private Double temperature;
    /** pH 值 */
    private Double ph;
    /** 氧化还原电位（mV） */
    private Double orp;

    /** 闸门 1..6：1=开，0=关 */
    private Integer relay1;
    private Integer relay2;
    private Integer relay3;
    private Integer relay4;
    private Integer relay5;
    private Integer relay6;

    /** 数据来源，见 {@link #SOURCE_MQTT} / {@link #SOURCE_MIGRATION} */
    private String source;
    /** 旧 MySQL 表的自增 id，仅迁移数据有值 */
    private Long legacyId;
    /** 入库时间（用于排查写入延迟） */
    private Instant createdAt;

    public WaterReading() {
    }

    /** 6 路闸门的状态数组，便于遍历和统计（长度固定为 6） */
    public int[] relayArray() {
        return new int[]{
                relay1 == null ? 0 : relay1,
                relay2 == null ? 0 : relay2,
                relay3 == null ? 0 : relay3,
                relay4 == null ? 0 : relay4,
                relay5 == null ? 0 : relay5,
                relay6 == null ? 0 : relay6
        };
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public Instant getTime() {
        return time;
    }

    public void setTime(Instant time) {
        this.time = time;
    }

    public Double getLevel() {
        return level;
    }

    public void setLevel(Double level) {
        this.level = level;
    }

    public Double getTemperature() {
        return temperature;
    }

    public void setTemperature(Double temperature) {
        this.temperature = temperature;
    }

    public Double getPh() {
        return ph;
    }

    public void setPh(Double ph) {
        this.ph = ph;
    }

    public Double getOrp() {
        return orp;
    }

    public void setOrp(Double orp) {
        this.orp = orp;
    }

    public Integer getRelay1() {
        return relay1;
    }

    public void setRelay1(Integer relay1) {
        this.relay1 = relay1;
    }

    public Integer getRelay2() {
        return relay2;
    }

    public void setRelay2(Integer relay2) {
        this.relay2 = relay2;
    }

    public Integer getRelay3() {
        return relay3;
    }

    public void setRelay3(Integer relay3) {
        this.relay3 = relay3;
    }

    public Integer getRelay4() {
        return relay4;
    }

    public void setRelay4(Integer relay4) {
        this.relay4 = relay4;
    }

    public Integer getRelay5() {
        return relay5;
    }

    public void setRelay5(Integer relay5) {
        this.relay5 = relay5;
    }

    public Integer getRelay6() {
        return relay6;
    }

    public void setRelay6(Integer relay6) {
        this.relay6 = relay6;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public Long getLegacyId() {
        return legacyId;
    }

    public void setLegacyId(Long legacyId) {
        this.legacyId = legacyId;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }
}
