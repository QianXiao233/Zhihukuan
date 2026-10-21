package com.zhka.entity;

import java.sql.Timestamp;

/** 水情采集记录，对应表 {@code water_log}（MQTT 上报后按间隔落库）。 */
public class WaterLog {

    private Long id;
    /** 水位（m） */
    private float level;
    /** 温度（℃） */
    private float temperature;
    private int relay1;
    private int relay2;
    private int relay3;
    private int relay4;
    private int relay5;
    private int relay6;
    /** pH 值 */
    private float ph;
    /** 氧化还原电位（mV） */
    private float orp;
    private Timestamp time;

    /** MyBatis 结果映射需要无参构造器 */
    public WaterLog() {
    }

    public WaterLog(float level, float temperature, int relay1, int relay2, int relay3, int relay4) {
        this.level = level;
        this.temperature = temperature;
        this.relay1 = relay1;
        this.relay2 = relay2;
        this.relay3 = relay3;
        this.relay4 = relay4;
        this.time = new Timestamp(System.currentTimeMillis());
    }

    public WaterLog(float level, float temperature, int relay1, int relay2, int relay3, int relay4,
                    int relay5, int relay6, float ph, float orp) {
        this(level, temperature, relay1, relay2, relay3, relay4);
        this.relay5 = relay5;
        this.relay6 = relay6;
        this.ph = ph;
        this.orp = orp;
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public float getLevel() {
        return level;
    }

    public void setLevel(float level) {
        this.level = level;
    }

    public float getTemperature() {
        return temperature;
    }

    public void setTemperature(float temperature) {
        this.temperature = temperature;
    }

    public int getRelay1() {
        return relay1;
    }

    public void setRelay1(int relay1) {
        this.relay1 = relay1;
    }

    public int getRelay2() {
        return relay2;
    }

    public void setRelay2(int relay2) {
        this.relay2 = relay2;
    }

    public int getRelay3() {
        return relay3;
    }

    public void setRelay3(int relay3) {
        this.relay3 = relay3;
    }

    public int getRelay4() {
        return relay4;
    }

    public void setRelay4(int relay4) {
        this.relay4 = relay4;
    }

    public int getRelay5() { return relay5; }

    public void setRelay5(int relay5) { this.relay5 = relay5; }

    public int getRelay6() { return relay6; }

    public void setRelay6(int relay6) { this.relay6 = relay6; }

    public float getPh() { return ph; }

    public void setPh(float ph) { this.ph = ph; }

    public float getOrp() { return orp; }

    public void setOrp(float orp) { this.orp = orp; }

    public Timestamp getTime() {
        return time;
    }

    public void setTime(Timestamp time) {
        this.time = time;
    }
}
