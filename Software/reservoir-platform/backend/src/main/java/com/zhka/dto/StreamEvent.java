package com.zhka.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 下发给前端的 SSE 事件，{@code type} 取值为 text / navigate / done / error。
 *
 * <p>与前端 {@code reservoir-platform/frontend/src/api/chat.js} 中的 {@code StreamEvent} 一一对应。
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record StreamEvent(
        String type,
        String content,
        @JsonProperty("conversation_id") String conversationId,
        String message,
        NavigateCommand command) {

    public static StreamEvent text(String content) {
        return new StreamEvent("text", content, null, null, null);
    }

    public static StreamEvent done(String conversationId) {
        return new StreamEvent("done", null, conversationId, null, null);
    }

    public static StreamEvent error(String message) {
        return new StreamEvent("error", null, null, message, null);
    }

    public static StreamEvent navigate(NavigateCommand command) {
        return new StreamEvent("navigate", null, null, null, command);
    }
}
