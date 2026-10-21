package com.zhka.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.zhka.common.ErrorMessages;
import com.zhka.config.ReservoirProperties;
import com.zhka.dto.ChatData;
import com.zhka.dto.StreamEvent;
import com.zhka.dto.UploadedFileData;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * Dify 调用封装。
 *
 * <p>职责：把 Dify 的 SSE 原始数据（agent_message / message / 工作流事件）
 * 归一化成前端契约里的 text / done / error 事件；同时负责文件上传与健康探测。
 */
@Service
public class DifyService {

    private static final Logger log = LoggerFactory.getLogger(DifyService.class);

    /** 多模态问答的响应可能较大，放宽 WebClient 缓冲上限 */
    private static final int MAX_IN_MEMORY_BYTES = 16 * 1024 * 1024;

    private final ReservoirProperties properties;
    private final ObjectMapper objectMapper;
    private final WebClient webClient;

    public DifyService(ReservoirProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.webClient = WebClient.builder()
                .baseUrl(properties.getDify().getApiBase())
                .defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + properties.getDify().getApiKey())
                .codecs(codecs -> codecs.defaultCodecs().maxInMemorySize(MAX_IN_MEMORY_BYTES))
                .build();
    }

    /** 密钥是否已配置（健康检查用） */
    public boolean isKeyConfigured() {
        String apiKey = properties.getDify().getApiKey();
        return apiKey != null && !apiKey.isBlank();
    }

    public String getApiBase() {
        return properties.getDify().getApiBase();
    }

    /**
     * 流式对话：返回归一化后的事件流。
     *
     * <p>Dify Chatflow 要求把变量放在 {@code inputs} 里，同时 {@code query} 也要传。
     */
    public Flux<StreamEvent> streamChat(String query, String conversationId, List<String> fileIds) {
        ObjectNode body = buildChatBody(query, conversationId, "streaming");

        // 多模态：把已上传文件的 id 传给 Dify
        if (fileIds != null && !fileIds.isEmpty()) {
            var files = body.putArray("files");
            for (String fileId : fileIds) {
                ObjectNode file = files.addObject();
                file.put("type", "image");
                file.put("transfer_method", "local_file");
                file.put("upload_file_id", fileId);
            }
        }

        return webClient.post()
                .uri("/chat-messages")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body.toString())
                .retrieve()
                .bodyToFlux(String.class)
                .timeout(Duration.ofSeconds(properties.getDify().getTimeout()))
                .flatMapIterable(this::parseChunk)
                .onErrorResume(e -> {
                    log.error("调用 Dify 失败: {}", e.getMessage());
                    return Flux.just(StreamEvent.error(ErrorMessages.friendly(e)));
                });
    }

    /** 阻塞式对话（调试用） */
    public Mono<ChatData> chatOnce(String query, String conversationId) {
        ObjectNode body = buildChatBody(query, conversationId, "blocking");

        return webClient.post()
                .uri("/chat-messages")
                .contentType(MediaType.APPLICATION_JSON)
                .bodyValue(body.toString())
                .retrieve()
                .bodyToMono(JsonNode.class)
                .timeout(Duration.ofSeconds(properties.getDify().getTimeout()))
                .map(node -> new ChatData(
                        node.path("answer").asText(""),
                        node.path("conversation_id").asText("")));
    }

    /**
     * 上传文件到 Dify，返回其 file id。
     *
     * <p>对应 Dify 的 {@code POST /files/upload}（multipart/form-data，字段名 file）。
     */
    public Mono<UploadedFileData> uploadFile(String filename, byte[] bytes, String mimeType) {
        MultipartBodyBuilder builder = new MultipartBodyBuilder();
        builder.part("file", bytes)
                .filename(filename)
                .contentType(MediaType.parseMediaType(
                        mimeType == null || mimeType.isBlank() ? MediaType.APPLICATION_OCTET_STREAM_VALUE : mimeType));
        builder.part("user", properties.getDify().getUser());

        return webClient.post()
                .uri("/files/upload")
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(BodyInserters.fromMultipartData(builder.build()))
                .retrieve()
                .bodyToMono(JsonNode.class)
                .timeout(Duration.ofSeconds(properties.getDify().getTimeout()))
                .map(node -> {
                    String id = node.path("id").asText("");
                    return new UploadedFileData(
                            id,
                            node.path("name").asText(filename),
                            node.path("size").asLong(bytes.length),
                            mimeType,
                            id,
                            null);
                });
    }

    /** 健康探测：尝试访问 Dify 的 parameters 接口 */
    public Mono<Boolean> ping() {
        return webClient.get()
                .uri("/parameters")
                .retrieve()
                .toBodilessEntity()
                .timeout(Duration.ofSeconds(5))
                .map(response -> true)
                .onErrorReturn(false);
    }

    /** 组装 /chat-messages 的请求体 */
    private ObjectNode buildChatBody(String query, String conversationId, String responseMode) {
        ObjectNode body = objectMapper.createObjectNode();
        body.putObject("inputs").put("query", query);
        body.put("query", query);
        body.put("response_mode", responseMode);
        body.put("conversation_id", conversationId == null ? "" : conversationId);
        body.put("user", properties.getDify().getUser());
        if ("streaming".equals(responseMode)) {
            body.put("auto_generate_name", false);
        }
        return body;
    }

    /**
     * 解析一行 Dify SSE 数据，产出零个或多个前端事件。
     *
     * <pre>
     * data: {"event":"message","answer":"文字","conversation_id":"..."}
     * data: {"event":"agent_message","answer":"..."}
     * data: {"event":"message_end","conversation_id":"..."}
     * data: {"event":"error","message":"..."}
     * </pre>
     */
    private List<StreamEvent> parseChunk(String raw) {
        List<StreamEvent> events = new ArrayList<>();
        if (raw == null || raw.isBlank()) {
            return events;
        }

        // WebClient 的 bodyToFlux(String) 已剥离 "data:" 前缀，但可能有残留
        String payload = raw.trim();
        if (payload.startsWith("data:")) {
            payload = payload.substring(5).trim();
        }
        if (payload.isEmpty() || "[DONE]".equals(payload)) {
            return events;
        }

        try {
            JsonNode node = objectMapper.readTree(payload);
            String event = node.path("event").asText("");

            switch (event) {
                case "message", "agent_message" -> {
                    String answer = node.path("answer").asText("");
                    if (!answer.isEmpty()) {
                        events.add(StreamEvent.text(answer));
                    }
                }
                case "message_end" -> events.add(StreamEvent.done(node.path("conversation_id").asText("")));
                case "error" -> events.add(StreamEvent.error(node.path("message").asText("Dify 返回错误")));
                default -> {
                    // 工作流类事件可能把最终文本放在 data.outputs 里
                    JsonNode data = node.path("data");
                    if (data.has("outputs")) {
                        String text = data.path("outputs").path("text").asText("");
                        if (!text.isEmpty()) {
                            events.add(StreamEvent.text(text));
                        }
                    }
                }
            }
        } catch (Exception e) {
            // 非 JSON 行（心跳等）直接忽略，避免打断流
            log.trace("跳过非 JSON 数据行: {}", payload);
        }
        return events;
    }
}
