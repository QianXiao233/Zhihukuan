package com.zhka.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.zhka.common.BusinessException;
import com.zhka.config.BusProperties;
import com.zhka.dto.BusMessageView;
import com.zhka.entity.BusClient;
import com.zhka.entity.BusMessage;
import com.zhka.repository.BusMessageQueryRepository;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.Condition;
import java.util.concurrent.locks.ReentrantLock;

/**
 * 消息中转核心：发布、长轮询领取、确认、失败重投。
 *
 * <p>投递语义是「至少一次」：消息落库后才会被领取；领取即加租约，
 * 租约到期没 ack 会被后台任务重新排队，因此消费方可能收到重复消息，
 * 需要按 {@code msgId} 做幂等。
 *
 * <p>长轮询唤醒：发布时 {@code signalAll} 唤醒本实例上等待的 pull 请求；
 * 等待循环每 2 秒回查一次数据库兜底（将来多实例部署时也能工作，只是延迟最多 2 秒）。
 */
@Service
public class BusService {

    private static final Logger log = LoggerFactory.getLogger(BusService.class);

    private static final int MAX_MESSAGE_TYPE_LENGTH = 100;
    private static final int MAX_CORRELATION_LENGTH = 100;
    private static final int MAX_ERROR_LENGTH = 500;
    private static final int MAX_LIMIT = 100;

    private final BusMessageQueryRepository query;
    private final BusProperties properties;
    private final ObjectMapper objectMapper;
    private final BusSubscriptionService subscriptions;

    private final ReentrantLock lock = new ReentrantLock();
    private final Condition arrived = lock.newCondition();

    private ScheduledExecutorService reaper;

    public BusService(BusMessageQueryRepository query, BusProperties properties, ObjectMapper objectMapper,
                      BusSubscriptionService subscriptions) {
        this.query = query;
        this.properties = properties;
        this.objectMapper = objectMapper;
        this.subscriptions = subscriptions;
    }

    @PostConstruct
    public void startReaper() {
        long interval = Math.max(5L, properties.getReaperIntervalSeconds());
        reaper = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "bus-reaper");
            thread.setDaemon(true);
            return thread;
        });
        reaper.scheduleWithFixedDelay(() -> {
            try {
                long[] result = query.releaseExpiredLeases(Instant.now(), properties.getMaxAttempts());
                if (result[0] > 0 || result[1] > 0) {
                    log.info("[总线] 回收过期租约：重投 {} 条，死信 {} 条", result[0], result[1]);
                }
            } catch (Exception e) {
                log.warn("[总线] 回收过期租约失败（MongoDB 可能不可用）: {}", e.getMessage());
            }
        }, interval, interval, TimeUnit.SECONDS);
        log.info("[总线] 已启动：租约 {}s，最多重试 {} 次，消息保留 {}s",
                properties.getLeaseSeconds(), properties.getMaxAttempts(), properties.getDefaultTtlSeconds());
    }

    @PreDestroy
    public void stopReaper() {
        if (reaper != null) {
            reaper.shutdownNow();
        }
    }

    /** 发布命令 */
    public record PublishCommand(String topic, String type, Map<String, Object> payload,
                                 String target, String correlationId, Long ttlSeconds) {
    }

    /** 拉取结果 */
    public record PullResult(List<BusMessageView> messages) {
    }

    /** 发布一条消息：校验主题与大小 → 落库 → 唤醒消费者并广播给浏览器 */
    public BusMessage publish(BusClient sender, PublishCommand command) {
        return publish(sender.getClientId(), command, null);
    }

    /** 平台内部发布（例如发布通知时推送到前端频道），来源记为 system */
    public BusMessage publishSystem(PublishCommand command) {
        return publish("system", command, null);
    }

    /** 平台内部发布，并限定只有这些用户名的浏览器连接会收到 */
    public BusMessage publishSystem(PublishCommand command, List<String> audience) {
        return publish("system", command, audience);
    }

    private BusMessage publish(String source, PublishCommand command) {
        return publish(source, command, null);
    }

    private BusMessage publish(String source, PublishCommand command, List<String> audience) {
        String topic = command.topic() == null ? "" : command.topic().trim();
        if (!BusTopicMatcher.isValidTopic(topic)) {
            throw new BusinessException("topic 不合法，只能是字母、数字、下划线、短横线和点，例如 alarm.dam1.level",
                    HttpStatus.BAD_REQUEST);
        }
        Map<String, Object> payload = command.payload() == null ? Map.of() : command.payload();
        long payloadBytes;
        try {
            payloadBytes = objectMapper.writeValueAsBytes(payload).length;
        } catch (Exception e) {
            throw new BusinessException("payload 不是合法的 JSON 对象", HttpStatus.BAD_REQUEST);
        }
        if (payloadBytes > properties.getMaxPayloadBytes()) {
            throw new BusinessException("payload 超过 " + properties.getMaxPayloadBytes() + " 字节，请改传引用/文件地址",
                    HttpStatus.PAYLOAD_TOO_LARGE);
        }

        long ttlSeconds = command.ttlSeconds() == null
                ? properties.getDefaultTtlSeconds()
                : command.ttlSeconds();
        ttlSeconds = Math.max(60L, Math.min(ttlSeconds, properties.getMaxTtlSeconds()));

        String target = blankToNull(command.target());
        String correlationId = truncate(blankToNull(command.correlationId()), MAX_CORRELATION_LENGTH);
        String type = truncate(blankToNull(command.type()), MAX_MESSAGE_TYPE_LENGTH);
        if (type == null) {
            int lastDot = topic.lastIndexOf('.');
            type = lastDot >= 0 ? topic.substring(lastDot + 1) : topic;
        }

        Instant now = Instant.now();
        BusMessage message = new BusMessage();
        message.setMsgId(UUID.randomUUID().toString());
        message.setTopic(topic);
        message.setType(type);
        message.setSource(source);
        message.setTarget(target);
        message.setAudience(audience);
        message.setPayload(payload);
        message.setCorrelationId(correlationId);
        message.setStatus(BusMessage.STATUS_PENDING);
        message.setAttempts(0);
        message.setNextAttemptAt(now);
        message.setCreatedAt(now);
        message.setUpdatedAt(now);
        message.setExpiresAt(now.plusSeconds(ttlSeconds));

        query.insert(message);
        signal();
        // 广播给浏览器：和队列的竞争消费互不影响，每个页面都能收到
        subscriptions.broadcast(message);
        log.debug("[总线] {} 发布 {} -> {}（msgId={}）", source, topic, target, message.getMsgId());
        return message;
    }

    /**
     * 长轮询领取消费：有消息立刻返回；没有就挂起等待，最多 {@code waitSeconds} 秒。
     *
     * @param requestedPattern 本次想订阅的主题模式（可空，空则用客户端全部订阅权限）
     * @param limit            本次最多领取条数
     * @param waitSeconds      最长等待秒数
     */
    public PullResult pull(BusClient client, String requestedPattern, int limit, int waitSeconds) {
        int size = Math.max(1, Math.min(limit, MAX_LIMIT));
        int wait = Math.max(0, Math.min(waitSeconds, properties.getMaxWaitSeconds()));
        String allowedRegex = BusTopicMatcher.toRegex(client.getAllowSubscribe());
        String requestedRegex = requestedPattern == null || requestedPattern.isBlank()
                ? null
                : BusTopicMatcher.toRegex(requestedPattern);
        Instant deadline = Instant.now().plusSeconds(wait);

        while (true) {
            Instant now = Instant.now();
            List<BusMessage> claimed = query.claim(client.getClientId(), allowedRegex, requestedRegex,
                    size, now, now.plusSeconds(properties.getLeaseSeconds()));
            if (!claimed.isEmpty()) {
                return new PullResult(claimed.stream().map(BusMessageView::from).toList());
            }
            long remaining = Duration.between(Instant.now(), deadline).toMillis();
            if (remaining <= 0) {
                return new PullResult(List.of());
            }
            await(Math.min(2000L, remaining));
        }
    }

    /** 确认消费，返回实际确认条数 */
    public long ack(BusClient client, List<String> msgIds) {
        return query.ack(client.getClientId(), msgIds, Instant.now());
    }

    /**
     * 报告消费失败：退避后重投，次数用尽进死信。
     *
     * @return pending / dead；消息不存在或不属于该消费者返回 null
     */
    public String nack(BusClient client, String msgId, String error) {
        if (msgId == null || msgId.isBlank()) {
            throw new BusinessException("缺少 msgId", HttpStatus.BAD_REQUEST);
        }
        return query.nack(client.getClientId(), msgId.trim(), truncate(error, MAX_ERROR_LENGTH),
                Instant.now(), properties.getMaxAttempts());
    }

    public Map<String, Long> counts() {
        return query.counts();
    }

    private void signal() {
        lock.lock();
        try {
            arrived.signalAll();
        } finally {
            lock.unlock();
        }
    }

    private void await(long millis) {
        lock.lock();
        try {
            arrived.await(millis, TimeUnit.MILLISECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            lock.unlock();
        }
    }

    private static String blankToNull(String value) {
        return value == null || value.isBlank() ? null : value.trim();
    }

    private static String truncate(String value, int max) {
        if (value == null || value.length() <= max) {
            return value;
        }
        return value.substring(0, max);
    }
}
