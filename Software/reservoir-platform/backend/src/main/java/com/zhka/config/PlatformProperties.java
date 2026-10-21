package com.zhka.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.ZoneId;

/**
 * 平台侧配置，前缀 {@code reservoir.platform}。
 *
 * <p>包含登录鉴权（JWT）与 MQTT 水情采集两部分：
 * {@code enabled} 是整体开关，{@code mqtt.*} 控制 broker / 主题 / 落库间隔。
 */
@ConfigurationProperties(prefix = "reservoir.platform")
public class PlatformProperties {

    /** 置 false 可整体关闭 MQTT 订阅与数据库写入（纯问答演示） */
    private boolean enabled = true;

    /** JWT 签名密钥（至少 32 字节）；留空则启动时随机生成 */
    private String jwtSecret = "";

    /** 展示用站点名，出现在告警推送与导出文件名里 */
    private String stationName = "水库监测站";

    /** 平台时区：无时区的时间参数、CSV、推送时间都按它解释 */
    private String zoneId = "Asia/Shanghai";

    private final Mqtt mqtt = new Mqtt();

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public String getJwtSecret() {
        return jwtSecret;
    }

    public void setJwtSecret(String jwtSecret) {
        this.jwtSecret = jwtSecret;
    }

    public String getStationName() {
        return stationName;
    }

    public void setStationName(String stationName) {
        this.stationName = stationName;
    }

    public String getZoneId() {
        return zoneId;
    }

    public void setZoneId(String zoneId) {
        this.zoneId = zoneId;
    }

    /** 解析时区；配置写错时退回 Asia/Shanghai，不影响启动 */
    public ZoneId zone() {
        try {
            return ZoneId.of(zoneId == null || zoneId.isBlank() ? "Asia/Shanghai" : zoneId.trim());
        } catch (Exception e) {
            return ZoneId.of("Asia/Shanghai");
        }
    }

    public Mqtt getMqtt() {
        return mqtt;
    }

    /** MQTT 订阅 RTU 上报数据 */
    public static class Mqtt {

        private boolean enabled = true;
        /** 形如 tcp://81.70.63.53:1883；broker 与本服务同机时写 tcp://127.0.0.1:1883（别写 localhost，它可能只解析到 ::1） */
        private String broker = "tcp://127.0.0.1:1883";
        private String clientId = "JavaService";
        /** EMQX 开启认证后必填；留空为匿名连接 */
        private String username = "";
        private String password = "";
        private String topic = "rtu/status";
        /** 最新一条数据落库的间隔（秒），默认 10 秒一条水情记录 */
        private long saveIntervalSeconds = 10;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getBroker() {
            return broker;
        }

        public void setBroker(String broker) {
            this.broker = broker;
        }

        public String getClientId() {
            return clientId;
        }

        public void setClientId(String clientId) {
            this.clientId = clientId;
        }

        public String getUsername() {
            return username;
        }

        public void setUsername(String username) {
            this.username = username;
        }

        public String getPassword() {
            return password;
        }

        public void setPassword(String password) {
            this.password = password;
        }

        public String getTopic() {
            return topic;
        }

        public void setTopic(String topic) {
            this.topic = topic;
        }


        public long getSaveIntervalSeconds() {
            return saveIntervalSeconds;
        }

        public void setSaveIntervalSeconds(long saveIntervalSeconds) {
            this.saveIntervalSeconds = saveIntervalSeconds;
        }
    }
}
