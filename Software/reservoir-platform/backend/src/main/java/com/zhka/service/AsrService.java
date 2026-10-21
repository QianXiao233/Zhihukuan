package com.zhka.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhka.common.BusinessException;
import com.zhka.config.ReservoirProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ByteArrayResource;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.LinkedMultiValueMap;
import org.springframework.util.MultiValueMap;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;

/**
 * 本地 FunASR 语音识别服务代理（默认端口 8001）。
 *
 * <p>前端把录音转成 16kHz 单声道 WAV 上传，这里转发给 {@code asr_server.py}。
 */
@Service
public class AsrService {

    private static final Logger log = LoggerFactory.getLogger(AsrService.class);

    private static final int MAX_IN_MEMORY_BYTES = 16 * 1024 * 1024;
    private static final Duration PING_TIMEOUT = Duration.ofSeconds(3);
    private static final Duration RECOGNIZE_TIMEOUT = Duration.ofSeconds(60);
    private static final String DEFAULT_FILENAME = "recording.wav";

    private final ReservoirProperties properties;
    private final ObjectMapper objectMapper;
    private final WebClient webClient;

    public AsrService(ReservoirProperties properties, ObjectMapper objectMapper) {
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.webClient = WebClient.builder()
                .baseUrl(properties.getAsr().getBaseUrl())
                .codecs(codecs -> codecs.defaultCodecs().maxInMemorySize(MAX_IN_MEMORY_BYTES))
                .build();
    }

    public boolean isEnabled() {
        return properties.getAsr().isEnabled();
    }

    /** 探测 ASR 服务是否在线；未启用时直接视为不可用 */
    public Mono<Boolean> ping() {
        if (!isEnabled()) {
            return Mono.just(false);
        }
        return webClient.get()
                .uri("/health")
                .retrieve()
                .toBodilessEntity()
                .timeout(PING_TIMEOUT)
                .map(response -> true)
                .onErrorReturn(false);
    }

    /** 转发音频并返回识别文本 */
    public Mono<String> recognize(byte[] audio, String filename) {
        String effectiveFilename = (filename == null || filename.isBlank()) ? DEFAULT_FILENAME : filename;

        MultiValueMap<String, Object> form = new LinkedMultiValueMap<>();
        form.add("file", new ByteArrayResource(audio) {
            @Override
            public String getFilename() {
                return effectiveFilename;
            }
        });

        return webClient.post()
                .uri("/asr")
                .contentType(MediaType.MULTIPART_FORM_DATA)
                .body(BodyInserters.fromMultipartData(form))
                .retrieve()
                .bodyToMono(String.class)
                .timeout(RECOGNIZE_TIMEOUT)
                .map(this::extractText)
                .onErrorResume(e -> {
                    log.warn("ASR 调用失败: {}", e.getMessage());
                    return Mono.error(new BusinessException("语音识别服务不可用，请确认 asr_server 已启动"));
                });
    }

    /** asr_server 返回 {@code {"text": "..."}}；解析失败按空文本处理，不打断前端录音流程 */
    private String extractText(String body) {
        try {
            return objectMapper.readTree(body).path("text").asText("");
        } catch (Exception e) {
            log.warn("ASR 返回内容无法解析: {}", body);
            return "";
        }
    }
}
