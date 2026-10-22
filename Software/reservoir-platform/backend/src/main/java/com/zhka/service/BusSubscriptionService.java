package com.zhka.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhka.entity.BusMessage;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * 浏览器通知频道：把总线上发布的消息实时扇出给所有 SSE 订阅者。
 *
 * <p>和 {@code /api/bus/pull} 的「竞争消费」不同，这里是**广播**：
 * 同一条消息会发给每个订阅了匹配主题的浏览器，谁也不会把消息“领走”。
 * 因此前端弹窗、提示音不会因为别的消费者先 ack 而丢失。
 *
 * <p>连接用 20 秒心跳保活（Nginx 默认 60 秒读超时），断线由浏览器自动重连，
 * 重连时用一次性票据重新订阅。
 */
@Service
public class BusSubscriptionService {

    private static final Logger log = LoggerFactory.getLogger(BusSubscriptionService.class);
    private static final long HEARTBEAT_SECONDS = 20L;

    private final ObjectMapper objectMapper;
    private final Map<String, Subscriber> subscribers = new ConcurrentHashMap<>();
    private ScheduledExecutorService heartbeat;

    public BusSubscriptionService(ObjectMapper objectMapper) {
        this.objectMapper = objectMapper;
    }

    private record Subscriber(String id, String username, String patterns, SseEmitter emitter) {
    }

    @PostConstruct
    public void startHeartbeat() {
        heartbeat = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "bus-sse-heartbeat");
            thread.setDaemon(true);
            return thread;
        });
        heartbeat.scheduleAtFixedRate(() -> {
            for (Subscriber subscriber : subscribers.values()) {
                try {
                    subscriber.emitter().send(SseEmitter.event().comment("ping"));
                } catch (Exception e) {
                    remove(subscriber.id());
                }
            }
        }, HEARTBEAT_SECONDS, HEARTBEAT_SECONDS, TimeUnit.SECONDS);
    }

    @PreDestroy
    public void stopHeartbeat() {
        if (heartbeat != null) {
            heartbeat.shutdownNow();
        }
        subscribers.values().forEach(subscriber -> {
            try {
                subscriber.emitter().complete();
            } catch (Exception ignored) {
                // 关闭阶段的异常忽略
            }
        });
        subscribers.clear();
    }

    /** 为一个浏览器建立订阅；{@code patterns} 是逗号分隔的主题模式 */
    public SseEmitter subscribe(String username, String patterns) {
        String id = UUID.randomUUID().toString();
        // 0 = 不设超时，靠心跳和客户端重连保活
        SseEmitter emitter = new SseEmitter(0L);
        Subscriber subscriber = new Subscriber(id, username, patterns, emitter);
        subscribers.put(id, subscriber);
        emitter.onCompletion(() -> remove(id));
        emitter.onTimeout(() -> remove(id));
        emitter.onError(error -> remove(id));
        try {
            emitter.send(SseEmitter.event().name("ready").data(Map.of(
                    "channel", patterns,
                    "subscriber", id)));
        } catch (IOException e) {
            remove(id);
        }
        log.debug("[总线] {} 订阅通知频道 {}（当前 {} 个连接）", username, patterns, subscribers.size());
        return emitter;
    }

    /** 广播一条消息给所有主题匹配的订阅者；发送失败的连接会被移除 */
    public void broadcast(BusMessage message) {
        if (subscribers.isEmpty()) {
            return;
        }
        String json;
        try {
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("msgId", message.getMsgId());
            data.put("topic", message.getTopic());
            data.put("type", message.getType());
            data.put("source", message.getSource());
            data.put("payload", message.getPayload());
            data.put("createdAt", message.getCreatedAt());
            json = objectMapper.writeValueAsString(data);
        } catch (Exception e) {
            log.warn("[总线] 通知序列化失败: {}", e.getMessage());
            return;
        }
        for (Subscriber subscriber : subscribers.values()) {
            if (!BusTopicMatcher.matchesAny(message.getTopic(), subscriber.patterns())) {
                continue;
            }
            // 定向通知只发给指定的用户
            if (message.getAudience() != null && !message.getAudience().contains(subscriber.username())) {
                continue;
            }
            try {
                subscriber.emitter().send(SseEmitter.event().name("bus").data(json));
            } catch (Exception e) {
                remove(subscriber.id());
            }
        }
    }

    public int connectionCount() {
        return subscribers.size();
    }

    private void remove(String id) {
        subscribers.remove(id);
    }
}
