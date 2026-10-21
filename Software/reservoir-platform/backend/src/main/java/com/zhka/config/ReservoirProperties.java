package com.zhka.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 外部服务配置：Dify / ASR / TTS / 消息推送。
 *
 * <p>通过 {@code @ConfigurationPropertiesScan} 注册，配置前缀 {@code reservoir}。
 */
@ConfigurationProperties(prefix = "reservoir")
public class ReservoirProperties {

    private final Dify dify = new Dify();
    private final Asr asr = new Asr();
    private final Tts tts = new Tts();
    private final Push push = new Push();
    private final Alert alert = new Alert();

    public Dify getDify() {
        return dify;
    }

    public Asr getAsr() {
        return asr;
    }

    public Tts getTts() {
        return tts;
    }

    public Push getPush() {
        return push;
    }

    public Alert getAlert() {
        return alert;
    }

    /** Dify 应用配置 */
    public static class Dify {

        /** 形如 http://host/v1 */
        private String apiBase = "http://127.0.0.1/v1";
        private String apiKey = "";
        private String user = "reservoir-user";
        /** 超时秒数 */
        private int timeout = 120;

        public String getApiBase() {
            return apiBase;
        }

        public void setApiBase(String apiBase) {
            this.apiBase = apiBase;
        }

        public String getApiKey() {
            return apiKey;
        }

        public void setApiKey(String apiKey) {
            this.apiKey = apiKey;
        }

        public String getUser() {
            return user;
        }

        public void setUser(String user) {
            this.user = user;
        }

        public int getTimeout() {
            return timeout;
        }

        public void setTimeout(int timeout) {
            this.timeout = timeout;
        }
    }

    /** 本地 FunASR 服务 */
    public static class Asr {

        private String baseUrl = "http://127.0.0.1:8001";
        private boolean enabled = true;

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }
    }

    /** 语音合成方式（browser 浏览器原生 / aliyun 阿里云，预留） */
    public static class Tts {

        private String provider = "browser";

        public String getProvider() {
            return provider;
        }

        public void setProvider(String provider) {
            this.provider = provider;
        }
    }

    /**
     * 消息推送（第三方推送服务）。
     *
     * <p>最终请求地址 = {@code baseUrl + "/" + token}，其中 token 由调用方在
     * {@code PushService.push(token, title, content)} 时传入，不写进配置；
     * 接口接受 GET 或 POST，参数为 {@code title} 与 {@code content}（支持文本 / markdown / html）。
     */
    public static class Push {

        /** 关掉可以整体停用推送，不发任何请求 */
        private boolean enabled = true;

        /** 推送接口基础地址，不含 token */
        private String baseUrl = "https://push.showdoc.com.cn/server/api/push";

        /** 单次推送超时秒数 */
        private int timeout = 5;

        /**
         * 兜底 token：数据库 {@code platform_setting.push.token} 没配置时使用。
         *
         * <p>正常应该在管理页填写，这里只给无数据库的演示环境或 CI 用；
         * 优先级是「数据库 > 环境变量 PUSH_TOKEN > 空」。
         */
        private String token = "";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public int getTimeout() {
            return timeout;
        }

        public void setTimeout(int timeout) {
            this.timeout = timeout;
        }

        public String getToken() {
            return token;
        }

        public void setToken(String token) {
            this.token = token;
        }
    }

    /**
     * 实时阈值告警。
     *
     * <p>MQTT 每收到一条数据都会比对阈值；真正推送受「冷却时间」约束：
     * 同一个指标在冷却窗口内只推一次，避免读数在阈值附近抖动时把推送通道打爆。
     */
    public static class Alert {

        /** 关掉只保留页面上的越界判断，不发任何推送 */
        private boolean enabled = true;

        /** 同一指标两次推送之间的最小间隔（分钟），0 表示不限制 */
        private int cooldownMinutes = 10;

        /** 登录异常告警的冷却时间（分钟），按账号维度 */
        private int loginCooldownMinutes = 5;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public int getCooldownMinutes() {
            return cooldownMinutes;
        }

        public void setCooldownMinutes(int cooldownMinutes) {
            this.cooldownMinutes = cooldownMinutes;
        }

        public int getLoginCooldownMinutes() {
            return loginCooldownMinutes;
        }

        public void setLoginCooldownMinutes(int loginCooldownMinutes) {
            this.loginCooldownMinutes = loginCooldownMinutes;
        }
    }
}
