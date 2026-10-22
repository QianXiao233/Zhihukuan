package com.zhka.controller;

import com.zhka.common.BusinessException;
import com.zhka.config.BusSseAuthFilter;
import com.zhka.dto.BusMessageView;
import com.zhka.entity.BusClient;
import com.zhka.entity.BusMessage;
import com.zhka.service.AuthService;
import com.zhka.service.BusClientService;
import com.zhka.service.BusService;
import com.zhka.service.BusSubscriptionService;
import com.zhka.service.BusTicketService;
import com.zhka.service.BusTopicMatcher;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 服务间消息中转接口：{@code /api/bus/**}。
 *
 * <p>所有接口都用服务密钥鉴权：{@code Authorization: Bearer <clientId>.<secret>}。
 * 典型调用顺序：
 * <pre>
 *   A: POST /publish   → 拿到 msgId
 *   B: GET  /pull      → 长轮询领取（默认最多挂 25 秒）
 *   B: POST /ack       → 确认消费
 *   B: POST /nack      → 处理失败，退避后重投
 * </pre>
 */
@RestController
@RequestMapping("/api/bus")
public class BusController {

    private final BusService bus;
    private final BusClientService clients;
    private final AuthService authService;
    private final BusTicketService tickets;
    private final BusSubscriptionService subscriptions;

    public BusController(BusService bus, BusClientService clients, AuthService authService,
                         BusTicketService tickets, BusSubscriptionService subscriptions) {
        this.bus = bus;
        this.clients = clients;
        this.authService = authService;
        this.tickets = tickets;
        this.subscriptions = subscriptions;
    }

    /**
     * 浏览器通知频道（默认 {@code ui.#}）。
     *
     * <p>登录用户先换一次性票据，再用票据建立 SSE；票据在 URL 里只出现一次，
     * 不会把 JWT 暴露给访问日志。浏览器只允许订阅 {@code ui.*}。
     */
    @PostMapping("/ticket")
    public Map<String, Object> ticket(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthService.AuthUser user = authService.verify(authorization);
        if (user == null) {
            throw new BusinessException("登录已失效，请重新登录", HttpStatus.UNAUTHORIZED);
        }
        String topic = "ui.#";
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("ticket", tickets.issue(user, topic));
        body.put("topic", topic);
        body.put("expiresIn", 60);
        return body;
    }

    @GetMapping(value = "/subscribe", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter subscribe(
            @RequestAttribute(BusSseAuthFilter.USER_ATTRIBUTE) String username,
            @RequestParam(value = "topic", defaultValue = "ui.#") String topic,
            HttpServletResponse response) {
        // 告诉 Nginx 不要缓冲，否则事件会攒着一起发
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Cache-Control", "no-cache");
        return subscriptions.subscribe(username, topic);
    }

    /** 频道连接数（排障用） */
    @GetMapping("/channel")
    public Map<String, Object> channel(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        requireClient(authorization);
        return Map.of("connections", subscriptions.connectionCount(), "tickets", tickets.pendingCount());
    }

    /** 发布请求体 */
    public record PublishRequest(String topic, String type, Map<String, Object> payload,
                                 String target, String correlationId, Long ttlSeconds) {
    }

    public record AckRequest(List<String> msgIds) {
    }

    public record NackRequest(String msgId, String error) {
    }

    @PostMapping("/publish")
    public Map<String, Object> publish(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody PublishRequest request) {
        BusClient client = requireClient(authorization);
        if (request.topic() == null || !BusTopicMatcher.matchesAny(request.topic(), client.getAllowPublish())) {
            throw new BusinessException("当前客户端无权发布到该主题：" + request.topic(), HttpStatus.FORBIDDEN);
        }
        if (request.target() != null && !request.target().isBlank() && !clients.isEnabled(request.target())) {
            throw new BusinessException("target 客户端不存在或已停用：" + request.target(), HttpStatus.BAD_REQUEST);
        }
        BusMessage message = bus.publish(client, new BusService.PublishCommand(
                request.topic(), request.type(), request.payload(),
                request.target(), request.correlationId(), request.ttlSeconds()));
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("msgId", message.getMsgId());
        result.put("topic", message.getTopic());
        result.put("type", message.getType());
        result.put("status", message.getStatus());
        result.put("expiresAt", message.getExpiresAt());
        return result;
    }

    @GetMapping("/pull")
    public Map<String, Object> pull(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam(required = false) String topic,
            @RequestParam(defaultValue = "20") int limit,
            @RequestParam(defaultValue = "25") int wait) {
        BusClient client = requireClient(authorization);
        BusService.PullResult result = bus.pull(client, topic, limit, wait);
        List<BusMessageView> messages = result.messages();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("count", messages.size());
        body.put("messages", messages);
        return body;
    }

    @PostMapping("/ack")
    public Map<String, Object> ack(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody AckRequest request) {
        BusClient client = requireClient(authorization);
        if (request.msgIds() == null || request.msgIds().isEmpty()) {
            throw new BusinessException("msgIds 不能为空", HttpStatus.BAD_REQUEST);
        }
        long acked = bus.ack(client, request.msgIds());
        return Map.of("acked", acked);
    }

    @PostMapping("/nack")
    public Map<String, Object> nack(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestBody NackRequest request) {
        BusClient client = requireClient(authorization);
        String status = bus.nack(client, request.msgId(), request.error());
        if (status == null) {
            throw new BusinessException("消息不存在、已确认或不属于当前客户端", HttpStatus.NOT_FOUND);
        }
        return Map.of("status", status);
    }

    /** 当前密钥对应的客户端信息，方便接入方自检 */
    @GetMapping("/me")
    public Map<String, Object> me(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        BusClient client = requireClient(authorization);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("clientId", client.getClientId());
        body.put("clientName", client.getClientName());
        body.put("allowPublish", client.getAllowPublish());
        body.put("allowSubscribe", client.getAllowSubscribe());
        return body;
    }

    /** 队列状态（待投递 / 处理中 / 已投递 / 死信） */
    @GetMapping("/status")
    public Map<String, Object> status(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        requireClient(authorization);
        return Map.of("counts", bus.counts());
    }

    private BusClient requireClient(String authorization) {
        BusClient client = clients.authenticate(authorization);
        if (client == null) {
            throw new BusinessException("服务密钥无效或客户端已停用", HttpStatus.UNAUTHORIZED);
        }
        return client;
    }
}
