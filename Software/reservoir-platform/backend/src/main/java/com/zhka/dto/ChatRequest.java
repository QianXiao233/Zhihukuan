package com.zhka.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.util.List;

/**
 * 对话请求：文字内容 + 可选的多模态文件 id。
 *
 * <p>对应前端 {@code /api/chat/stream} 的请求体：
 * {@code {query, conversation_id, file_ids}}。
 */
public record ChatRequest(
        String query,
        @JsonProperty("conversation_id") String conversationId,
        @JsonProperty("file_ids") List<String> fileIds) {
}
