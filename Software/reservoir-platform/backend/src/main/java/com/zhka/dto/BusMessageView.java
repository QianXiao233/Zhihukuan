package com.zhka.dto;

import com.zhka.entity.BusMessage;

import java.time.Instant;
import java.util.Map;

/** 总线下发给消费方的消息视图（隐藏租约、消费者等内部字段）。 */
public record BusMessageView(String msgId, String topic, String type, String source, String target,
                             Map<String, Object> payload, String correlationId, Instant createdAt,
                             Instant expiresAt, int attempts) {

    public static BusMessageView from(BusMessage message) {
        return new BusMessageView(message.getMsgId(), message.getTopic(), message.getType(),
                message.getSource(), message.getTarget(), message.getPayload(),
                message.getCorrelationId(), message.getCreatedAt(), message.getExpiresAt(),
                message.getAttempts());
    }
}
