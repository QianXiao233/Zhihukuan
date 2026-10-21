package com.zhka.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhka.common.ApiResponse;
import com.zhka.common.ErrorMessages;
import com.zhka.dto.ChatData;
import com.zhka.dto.ChatRequest;
import com.zhka.dto.StreamEvent;
import com.zhka.service.ChatService;
import org.springframework.http.MediaType;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

/**
 * 对话接口。
 *
 * <p>前端契约（与 {@code reservoir-platform/frontend/src/api/chat.js} 对齐）：
 * <ul>
 *   <li>{@code POST /api/chat/stream} 流式，事件 {@code data: {"type":"text"|"navigate"|"done"|"error", ...}}</li>
 *   <li>{@code POST /api/chat} 阻塞式（调试用），返回 {@code {code,message,data}}</li>
 * </ul>
 * 业务编排在 {@link ChatService}，本类只负责流式传输格式（SSE）与响应包装。
 */
@RestController
@RequestMapping("/api")
public class ChatController {

    private static final String SERIALIZE_ERROR_JSON = "{\"type\":\"error\",\"message\":\"事件序列化失败\"}";

    private final ChatService chatService;
    private final ObjectMapper objectMapper;

    public ChatController(ChatService chatService, ObjectMapper objectMapper) {
        this.chatService = chatService;
        this.objectMapper = objectMapper;
    }

    /** 流式对话 */
    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public Flux<ServerSentEvent<String>> stream(@RequestBody ChatRequest request) {
        return chatService.stream(request.query(), request.conversationId(), request.fileIds())
                .map(this::toSse);
    }

    /** 阻塞式对话（调试用） */
    @PostMapping("/chat")
    public Mono<ApiResponse<ChatData>> chat(@RequestBody ChatRequest request) {
        if (ChatService.normalizeQuery(request.query()).isEmpty()) {
            return Mono.just(ApiResponse.error(400, ChatService.EMPTY_QUERY_MESSAGE));
        }
        return chatService.chatOnce(request.query(), request.conversationId())
                .map(ApiResponse::ok)
                .onErrorResume(e -> Mono.just(
                        ApiResponse.error(ErrorMessages.errorCode(e), ErrorMessages.friendly(e))));
    }

    /** 组装 SSE 事件（data 为 JSON 字符串） */
    private ServerSentEvent<String> toSse(StreamEvent event) {
        try {
            return ServerSentEvent.<String>builder()
                    .data(objectMapper.writeValueAsString(event))
                    .build();
        } catch (Exception e) {
            return ServerSentEvent.<String>builder()
                    .data(SERIALIZE_ERROR_JSON)
                    .build();
        }
    }
}
