package com.zhka.entity;

import java.time.LocalDateTime;

/**
 * 总线客户端（服务身份与主题权限），对应 MySQL 表 {@code bus_client}。
 *
 * <p>配置类数据留在 MySQL；只有消息本体进 MongoDB。
 * {@code secretHash} 是密钥的 SHA-256，明文只在创建/轮换时返回一次。
 */
public class BusClient {

    private String clientId;
    private String clientName;
    /** 密钥的 SHA-256（十六进制） */
    private String secretHash;
    /** 允许发布的主题，逗号分隔，支持 * 和 #；默认 # */
    private String allowPublish;
    /** 允许订阅的主题，逗号分隔，支持 * 和 #；默认 # */
    private String allowSubscribe;
    private boolean enabled;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;

    public String getClientId() {
        return clientId;
    }

    public void setClientId(String clientId) {
        this.clientId = clientId;
    }

    public String getClientName() {
        return clientName;
    }

    public void setClientName(String clientName) {
        this.clientName = clientName;
    }

    public String getSecretHash() {
        return secretHash;
    }

    public void setSecretHash(String secretHash) {
        this.secretHash = secretHash;
    }

    public String getAllowPublish() {
        return allowPublish;
    }

    public void setAllowPublish(String allowPublish) {
        this.allowPublish = allowPublish;
    }

    public String getAllowSubscribe() {
        return allowSubscribe;
    }

    public void setAllowSubscribe(String allowSubscribe) {
        this.allowSubscribe = allowSubscribe;
    }

    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(LocalDateTime createdAt) {
        this.createdAt = createdAt;
    }

    public LocalDateTime getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(LocalDateTime updatedAt) {
        this.updatedAt = updatedAt;
    }
}
