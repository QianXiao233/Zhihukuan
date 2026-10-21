package com.zhka.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 阻塞式对话结果。 */
public record ChatData(
        String reply,
        @JsonProperty("conversation_id") String conversationId) {
}
