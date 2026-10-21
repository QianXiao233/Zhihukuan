package com.zhka.entity;

/**
 * 平台键值配置，对应表 {@code platform_setting}。
 *
 * <p>用来存「需要运维在页面里改、但不能写进配置文件」的东西，
 * 目前是推送 token / 开关 / 冷却时间。表结构上只有三列，
 * 后续加配置项不用再改表。
 */
public class PlatformSetting {

    private String settingKey;
    private String settingValue;

    public PlatformSetting() {
    }

    public PlatformSetting(String settingKey, String settingValue) {
        this.settingKey = settingKey;
        this.settingValue = settingValue;
    }

    public String getSettingKey() {
        return settingKey;
    }

    public void setSettingKey(String settingKey) {
        this.settingKey = settingKey;
    }

    public String getSettingValue() {
        return settingValue;
    }

    public void setSettingValue(String settingValue) {
        this.settingValue = settingValue;
    }
}
