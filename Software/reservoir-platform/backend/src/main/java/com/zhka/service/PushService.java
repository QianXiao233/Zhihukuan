package com.zhka.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhka.config.ReservoirProperties;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.util.UriUtils;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/**
 * 消息推送服务。
 *
 * <p>请求地址由「配置里的基础地址 + 调用时传入的 token」拼成：
 * <pre>
 *   {baseUrl}/{token}
 *   例：https://push.showdoc.com.cn/server/api/push/&lt;token&gt;
 * </pre>
 * 接口接受 {@code GET} 或 {@code POST}（这里统一用 POST 表单，避免内容过长被 URL 长度限制），
 * 参数为 {@code title}（标题）与 {@code content}（内容，支持文本 / markdown / html）。
 *
 * <p>token 不写进配置文件，由调用方传入，因此同一个服务可以推送到多个频道 / 多个人：
 * <pre>{@code
 * // ① 纯文本：自己拼标题和正文
 * PushService.PushResult result = pushService.push(token, "水位预警", "当前库水位 129.2 m");
 *
 * // ② 用内置 HTML 模板（推荐）：模板见 PushTemplate
 * pushService.pushAsync(token, PushTemplate.WATER_LEVEL_ALERT, Map.of(
 *         "damName", "青龙水库", "currentLevel", "129.20", "threshold", "129.00",
 *         "exceeded", "0.20", "unit", "m", "status", "超汛限", "time", "2026-10-19 19:40"));
 * }</pre>
 *
 * <p>唯一需要配置的是 {@code reservoir.push.base-url}（已内置默认值），
 * 以及可选的 {@code enabled} / {@code timeout}。
 */
@Service
public class PushService {

    private static final Logger log = LoggerFactory.getLogger(PushService.class);

    /** 响应体只截取前若干字符写日志，避免把整篇 markdown 回显进日志 */
    private static final int MAX_LOGGED_BODY = 200;

    /** token 在日志里只保留的头尾长度 */
    private static final int TOKEN_HEAD = 6;
    private static final int TOKEN_TAIL = 4;

    private static final int SHUTDOWN_WAIT_SECONDS = 3;

    private final ReservoirProperties.Push properties;
    private final ObjectMapper objectMapper;
    private final WebClient webClient;
    private final ExecutorService executor;

    public PushService(ReservoirProperties properties, ObjectMapper objectMapper) {
        this.properties = properties.getPush();
        this.objectMapper = objectMapper;
        this.webClient = WebClient.builder().build();
        this.executor = Executors.newSingleThreadExecutor(runnable -> {
            Thread thread = new Thread(runnable, "push-sender");
            thread.setDaemon(true);
            return thread;
        });

        if (isEnabled()) {
            log.info("[推送] 已启用，接口 {}，超时 {}s（token 由调用方传入）",
                    this.properties.getBaseUrl(), this.properties.getTimeout());
        } else {
            log.info("[推送] 已禁用（reservoir.push.enabled=false 或 base-url 为空），推送不会生效");
        }
    }

    /**
     * 推送结果。
     *
     * @param success 是否推送成功（HTTP 2xx 且 {@code error_code == 0}）
     * @param status  HTTP 状态码；本地校验失败或网络异常时为 0 / -1
     * @param message 服务端返回的 {@code error_message}（或响应体摘要）、失败原因
     */
    public record PushResult(boolean success, int status, String message) {

        static PushResult ok(int status, String body) {
            return new PushResult(true, status, body);
        }

        static PushResult fail(int status, String message) {
            return new PushResult(false, status, message);
        }
    }

    /** 是否可用：开关打开且配置了基础地址 */
    public boolean isEnabled() {
        String baseUrl = properties.getBaseUrl();
        return properties.isEnabled() && baseUrl != null && !baseUrl.isBlank();
    }

    /**
     * 同步推送，失败不抛异常（返回 {@link PushResult} 供调用方判断）。
     *
     * @param token   推送 token（请求地址最后一段），不能为空
     * @param title   消息标题，必填
     * @param content 消息内容，必填；支持文本 / markdown / html
     */
    public PushResult push(String token, String title, String content) {
        if (!isEnabled()) {
            return PushResult.fail(0, "推送已禁用或未配置基础地址");
        }
        if (isBlank(token)) {
            return PushResult.fail(0, "推送 token 不能为空");
        }
        if (isBlank(title)) {
            return PushResult.fail(0, "推送标题不能为空");
        }
        if (isBlank(content)) {
            return PushResult.fail(0, "推送内容不能为空");
        }

        String endpoint = endpoint(token);
        PushResult result = send(endpoint, title, content).block(blockTimeout());
        if (result == null) {
            return PushResult.fail(-1, "推送未返回结果");
        }

        if (result.success()) {
            log.info("[推送] 成功 token={} title={} status={}", maskToken(token), title, result.status());
        } else {
            log.warn("[推送] 失败 token={} title={} status={} 响应={}",
                    maskToken(token), title, result.status(), result.message());
        }
        return result;
    }

    /**
     * 按模板推送（同步）：标题与 HTML 正文由 {@link PushTemplate} 渲染。
     *
     * <p>缺少模板变量时不发消息，直接返回失败并指出缺哪个变量。
     */
    public PushResult push(String token, PushTemplate template, Map<String, Object> variables) {
        if (template == null) {
            return PushResult.fail(0, "推送模板不能为空");
        }
        String title;
        String content;
        try {
            title = template.renderTitle(variables);
            content = template.renderHtml(variables);
        } catch (IllegalArgumentException e) {
            log.warn("[推送] 模板渲染失败 template={}: {}", template, e.getMessage());
            return PushResult.fail(0, e.getMessage());
        }
        return push(token, title, content);
    }

    /**
     * 异步推送：立即返回，实际发送在守护线程里完成。
     *
     * <p>适合放在业务主流程中（如台账变更、问答异常），推送失败只记日志，不影响主流程。
     */
    public void pushAsync(String token, String title, String content) {
        if (!isEnabled()) {
            log.debug("[推送] 已禁用，跳过 title={}", title);
            return;
        }
        executor.execute(() -> push(token, title, content));
    }

    /** 按模板异步推送，渲染或发送失败都只记日志 */
    public void pushAsync(String token, PushTemplate template, Map<String, Object> variables) {
        if (!isEnabled()) {
            log.debug("[推送] 已禁用，跳过 template={}", template);
            return;
        }
        executor.execute(() -> push(token, template, variables));
    }

    /**
     * 按模板异步推送，并把结果回调给调用方。
     *
     * <p>和上面两个 {@code pushAsync} 的区别：即使推送被禁用或参数不合法，
     * 也会回调一次失败结果（而不是静默返回），调用方才能把「为什么没发出去」记下来。
     * 回调在推送线程执行，实现里不要做阻塞操作。
     */
    public void pushAsync(String token, PushTemplate template, Map<String, Object> variables,
                          Consumer<PushResult> onComplete) {
        Consumer<PushResult> callback = onComplete == null ? result -> { } : onComplete;
        if (!isEnabled()) {
            callback.accept(PushResult.fail(0, "推送已禁用或未配置基础地址"));
            return;
        }
        executor.execute(() -> {
            PushResult result;
            try {
                result = push(token, template, variables);
            } catch (Exception e) {
                result = PushResult.fail(-1, e.getMessage() == null ? "推送异常" : e.getMessage());
            }
            try {
                callback.accept(result);
            } catch (Exception e) {
                log.warn("[推送] 回调处理异常: {}", e.getMessage());
            }
        });
    }

    @PreDestroy
    public void shutdown() {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(SHUTDOWN_WAIT_SECONDS, TimeUnit.SECONDS)) {
                executor.shutdownNow();
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            executor.shutdownNow();
        }
    }

    /** 拼接请求地址：{baseUrl}/{token}，去掉基础地址末尾多余的斜杠，并对 token 做路径编码 */
    private String endpoint(String token) {
        String baseUrl = properties.getBaseUrl().trim();
        while (baseUrl.endsWith("/")) {
            baseUrl = baseUrl.substring(0, baseUrl.length() - 1);
        }
        return baseUrl + "/" + UriUtils.encodePathSegment(token.trim(), StandardCharsets.UTF_8);
    }

    /** 发一次 POST 表单；非 2xx 也返回结果而不抛异常 */
    private Mono<PushResult> send(String endpoint, String title, String content) {
        return webClient.post()
                .uri(endpoint)
                .contentType(MediaType.APPLICATION_FORM_URLENCODED)
                .body(BodyInserters.fromFormData("title", title).with("content", content))
                .exchangeToMono(response -> response.bodyToMono(String.class)
                        .defaultIfEmpty("")
                        .map(body -> interpret(response.statusCode().value(), body)))
                .timeout(requestTimeout())
                .onErrorResume(error -> {
                    log.warn("[推送] 请求异常: {}", error.getMessage());
                    return Mono.just(PushResult.fail(-1,
                            error.getMessage() == null ? "推送请求异常" : error.getMessage()));
                });
    }

    /**
     * 解释响应：该服务在业务失败时同样返回 200，靠响应体里的 {@code error_code} 区分
     * （0 为成功），所以不能只看 HTTP 状态码。
     */
    private PushResult interpret(int status, String body) {
        if (status < 200 || status >= 300) {
            return PushResult.fail(status, abbreviate(body));
        }
        JsonNode node = readJson(body);
        if (node != null && node.has("error_code")) {
            int errorCode = node.path("error_code").asInt(0);
            String errorMessage = node.path("error_message").asText("");
            return new PushResult(errorCode == 0, status,
                    errorMessage.isEmpty() ? abbreviate(body) : errorMessage);
        }
        return PushResult.ok(status, abbreviate(body));
    }

    /** 仅当响应体是 JSON 对象时才解析；纯文本 / HTML 等返回 null，按原文处理 */
    private JsonNode readJson(String body) {
        if (body == null || body.isBlank() || body.strip().charAt(0) != '{') {
            return null;
        }
        try {
            return objectMapper.readTree(body);
        } catch (Exception e) {
            return null;
        }
    }

    private Duration requestTimeout() {
        return Duration.ofSeconds(Math.max(1, properties.getTimeout()));
    }

    /** block 的等待时间要比请求超时略长，让 timeout 自己先生效并产生结果 */
    private Duration blockTimeout() {
        return requestTimeout().plusSeconds(2);
    }

    /** 日志里只暴露 token 的头尾，避免完整凭据落到日志文件 */
    private static String maskToken(String token) {
        String value = token.trim();
        if (value.length() <= TOKEN_HEAD + TOKEN_TAIL) {
            return "******";
        }
        return value.substring(0, TOKEN_HEAD) + "…" + value.substring(value.length() - TOKEN_TAIL);
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static String abbreviate(String text) {
        if (text == null) {
            return "";
        }
        String singleLine = text.strip();
        return singleLine.length() <= MAX_LOGGED_BODY
                ? singleLine
                : singleLine.substring(0, MAX_LOGGED_BODY) + "…";
    }
}
