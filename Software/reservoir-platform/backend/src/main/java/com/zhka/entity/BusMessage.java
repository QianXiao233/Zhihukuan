package com.zhka.entity;

import org.springframework.data.annotation.Id;
import org.springframework.data.mongodb.core.mapping.Document;

import java.time.Instant;
import java.util.Map;

/**
 * 服务间中转消息，集合 {@code bus_messages}。
 *
 * <p>链路：服务 A {@code POST /api/bus/publish} → 本文档落库 → 服务 B
 * {@code GET /api/bus/pull} 长轮询领取 → {@code POST /api/bus/ack} 确认。
 *
 * <p>投递语义是「至少一次」：
 * <ul>
 *   <li>领取时 {@code status=processing} 并加 {@code lockedUntil} 租约；</li>
 *   <li>租约过期没 ack 的消息会被重新发放（可能重复，消费方按 {@link #msgId} 幂等）；</li>
 *   <li>领取次数超过上限进 {@code dead}（死信），不再自动投递；</li>
 *   <li>{@code expiresAt} 上建 TTL 索引，到期后 MongoDB 自动删除（含已投递的历史）。</li>
 * </ul>
 *
 * <p>为什么放 MongoDB：消息是写多读少、结构不固定、按时间自动过期的数据，
 * TTL 索引和文档模型比 MySQL 更合适；配置类数据（客户端、权限）仍在 MySQL。
 */
@Document(collection = BusMessage.COLLECTION)
public class BusMessage {

    public static final String COLLECTION = "bus_messages";

    /** 待投递 */
    public static final String STATUS_PENDING = "pending";
    /** 已被某个消费者领取，等待 ack */
    public static final String STATUS_PROCESSING = "processing";
    /** 已确认消费 */
    public static final String STATUS_DELIVERED = "delivered";
    /** 重试次数耗尽，死信 */
    public static final String STATUS_DEAD = "dead";

    @Id
    private String id;

    /** 业务消息 id（UUID），消费方幂等键 */
    private String msgId;

    /** 主题，如 {@code alarm.dam1.level} */
    private String topic;

    /** 消息类型，缺省取主题最后一段 */
    private String type;

    /** 发布方 clientId */
    private String source;

    /** 指定消费方 clientId；为空表示广播（任何有订阅权限的客户端可领） */
    private String target;

    /**
     * 浏览器通知的接收人（仅 SSE 广播用）：为空表示所有订阅者，
     * 否则只有这些用户名的连接会收到，避免定向通知泄漏给其他账号。
     */
    private java.util.List<String> audience;

    /** 业务负载（JSON 对象），限制大小 */
    private Map<String, Object> payload;

    /** 关联 id，便于一次异常链路的多个消息串起来 */
    private String correlationId;

    /** 见 STATUS_* 常量 */
    private String status;

    /** 当前领取者 clientId */
    private String consumer;

    /** 已领取次数（含重试） */
    private int attempts;

    /** 下次可领取时间（重试退避） */
    private Instant nextAttemptAt;

    /** 租约到期时间；过期后允许别人重新领取 */
    private Instant lockedUntil;

    private Instant createdAt;
    private Instant updatedAt;
    private Instant deliveredAt;
    /** 到期由 TTL 索引删除 */
    private Instant expiresAt;

    /** 最近一次失败原因 */
    private String lastError;

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getMsgId() {
        return msgId;
    }

    public void setMsgId(String msgId) {
        this.msgId = msgId;
    }

    public String getTopic() {
        return topic;
    }

    public void setTopic(String topic) {
        this.topic = topic;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getSource() {
        return source;
    }

    public void setSource(String source) {
        this.source = source;
    }

    public String getTarget() {
        return target;
    }

    public void setTarget(String target) {
        this.target = target;
    }

    public java.util.List<String> getAudience() {
        return audience;
    }

    public void setAudience(java.util.List<String> audience) {
        this.audience = audience;
    }

    public Map<String, Object> getPayload() {
        return payload;
    }

    public void setPayload(Map<String, Object> payload) {
        this.payload = payload;
    }

    public String getCorrelationId() {
        return correlationId;
    }

    public void setCorrelationId(String correlationId) {
        this.correlationId = correlationId;
    }

    public String getStatus() {
        return status;
    }

    public void setStatus(String status) {
        this.status = status;
    }

    public String getConsumer() {
        return consumer;
    }

    public void setConsumer(String consumer) {
        this.consumer = consumer;
    }

    public int getAttempts() {
        return attempts;
    }

    public void setAttempts(int attempts) {
        this.attempts = attempts;
    }

    public Instant getNextAttemptAt() {
        return nextAttemptAt;
    }

    public void setNextAttemptAt(Instant nextAttemptAt) {
        this.nextAttemptAt = nextAttemptAt;
    }

    public Instant getLockedUntil() {
        return lockedUntil;
    }

    public void setLockedUntil(Instant lockedUntil) {
        this.lockedUntil = lockedUntil;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Instant updatedAt) {
        this.updatedAt = updatedAt;
    }

    public Instant getDeliveredAt() {
        return deliveredAt;
    }

    public void setDeliveredAt(Instant deliveredAt) {
        this.deliveredAt = deliveredAt;
    }

    public Instant getExpiresAt() {
        return expiresAt;
    }

    public void setExpiresAt(Instant expiresAt) {
        this.expiresAt = expiresAt;
    }

    public String getLastError() {
        return lastError;
    }

    public void setLastError(String lastError) {
        this.lastError = lastError;
    }
}
