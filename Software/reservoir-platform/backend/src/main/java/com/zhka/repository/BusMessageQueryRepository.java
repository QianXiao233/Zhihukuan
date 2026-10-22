package com.zhka.repository;

import com.zhka.entity.BusMessage;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.core.FindAndModifyOptions;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.index.Index;
import org.springframework.data.mongodb.core.index.IndexOperations;
import org.springframework.data.mongodb.core.query.Criteria;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.data.mongodb.core.query.Update;
import org.springframework.stereotype.Repository;

import java.time.Duration;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 中转消息的队列操作（领取 / 确认 / 重试 / 死信 / 统计）。
 *
 * <p>MongoDB 没有 MySQL 的 {@code SELECT ... FOR UPDATE SKIP LOCKED}，
 * 所以用「租约」实现同样的效果：领取时原子地把状态改成 {@code processing}
 * 并写入 {@code lockedUntil}，到期未 ack 的消息在条件查询里重新变成可领取。
 */
@Repository
public class BusMessageQueryRepository {

    private final MongoTemplate mongo;

    /** 索引只创建一次（和 WaterReading 一样懒创建，避免启动时连库） */
    private volatile boolean indexReady = false;

    public BusMessageQueryRepository(MongoTemplate mongo) {
        this.mongo = mongo;
    }

    /**
     * 建集合与索引。
     *
     * <ul>
     *   <li>{@code expiresAt} TTL 索引：到期自动删除，不用写清理任务；</li>
     *   <li>{@code msgId} 唯一：消费方幂等，也防重复发布；</li>
     *   <li>状态 + 下次投递时间 + 创建时间：领取时走这个复合索引。</li>
     * </ul>
     */
    public void ensureIndexes() {
        if (indexReady) {
            return;
        }
        synchronized (this) {
            if (indexReady) {
                return;
            }
            IndexOperations operations = mongo.indexOps(BusMessage.class);
            operations.ensureIndex(new Index().on("expiresAt", Sort.Direction.ASC).expire(Duration.ZERO));
            operations.ensureIndex(new Index().on("msgId", Sort.Direction.ASC).unique());
            operations.ensureIndex(new Index()
                    .on("status", Sort.Direction.ASC)
                    .on("nextAttemptAt", Sort.Direction.ASC)
                    .on("createdAt", Sort.Direction.ASC));
            operations.ensureIndex(new Index()
                    .on("topic", Sort.Direction.ASC)
                    .on("status", Sort.Direction.ASC)
                    .on("createdAt", Sort.Direction.ASC));
            operations.ensureIndex(new Index()
                    .on("target", Sort.Direction.ASC)
                    .on("status", Sort.Direction.ASC));
            indexReady = true;
        }
    }

    /** 落库，返回带 _id 的文档 */
    public BusMessage insert(BusMessage message) {
        ensureIndexes();
        return mongo.insert(message);
    }

    /**
     * 原子领取最多 {@code limit} 条。
     *
     * @param clientId       领取方
     * @param allowedRegex   客户端订阅权限正则；null 表示不限
     * @param requestedRegex 本次请求的主题正则；null 表示不限
     * @param now            当前时间
     * @param lockUntil      租约到期时间
     */
    public List<BusMessage> claim(String clientId, String allowedRegex, String requestedRegex,
                                  int limit, Instant now, Instant lockUntil) {
        ensureIndexes();
        List<BusMessage> claimed = new ArrayList<>();
        for (int index = 0; index < limit; index++) {
            Query query = new Query(criteria(clientId, allowedRegex, requestedRegex, now))
                    .with(Sort.by(Sort.Direction.ASC, "createdAt").and(Sort.by(Sort.Direction.ASC, "_id")))
                    .limit(1);
            Update update = new Update()
                    .set("status", BusMessage.STATUS_PROCESSING)
                    .set("consumer", clientId)
                    .set("lockedUntil", lockUntil)
                    .set("updatedAt", now)
                    .inc("attempts", 1);
            BusMessage message = mongo.findAndModify(query, update,
                    FindAndModifyOptions.options().returnNew(true), BusMessage.class);
            if (message == null) {
                break;
            }
            claimed.add(message);
        }
        return claimed;
    }

    private Criteria criteria(String clientId, String allowedRegex, String requestedRegex, Instant now) {
        List<Criteria> all = new ArrayList<>();
        all.add(Criteria.where("status").is(BusMessage.STATUS_PENDING));
        all.add(Criteria.where("nextAttemptAt").lte(now));
        all.add(Criteria.where("expiresAt").gt(now));
        // 没有被锁，或者锁已过期
        all.add(new Criteria().orOperator(
                Criteria.where("lockedUntil").is(null),
                Criteria.where("lockedUntil").lte(now)));
        // 广播（target 为空/缺失）或点名给自己
        all.add(new Criteria().orOperator(
                Criteria.where("target").is(null),
                Criteria.where("target").is(clientId)));
        if (allowedRegex != null) {
            all.add(Criteria.where("topic").regex(allowedRegex));
        }
        if (requestedRegex != null) {
            all.add(Criteria.where("topic").regex(requestedRegex));
        }
        return new Criteria().andOperator(all.toArray(new Criteria[0]));
    }

    /** 确认消费；只允许领取者本人确认 */
    public long ack(String clientId, Collection<String> msgIds, Instant now) {
        if (msgIds == null || msgIds.isEmpty()) {
            return 0;
        }
        Query query = new Query(Criteria.where("msgId").in(msgIds)
                .and("consumer").is(clientId)
                .and("status").is(BusMessage.STATUS_PROCESSING));
        Update update = new Update()
                .set("status", BusMessage.STATUS_DELIVERED)
                .set("deliveredAt", now)
                .set("updatedAt", now)
                .unset("lockedUntil");
        return mongo.updateMulti(query, update, BusMessage.class).getModifiedCount();
    }

    /**
     * 消费失败：退避后重投，次数用尽进死信。
     *
     * @return 处理后的状态（pending/retry/dead）；消息不存在或不属于该消费者返回 null
     */
    public String nack(String clientId, String msgId, String error, Instant now, int maxAttempts) {
        BusMessage message = mongo.findOne(new Query(Criteria.where("msgId").is(msgId)
                .and("consumer").is(clientId)
                .and("status").is(BusMessage.STATUS_PROCESSING)), BusMessage.class);
        if (message == null) {
            return null;
        }
        boolean dead = message.getAttempts() >= maxAttempts;
        Update update = new Update()
                .set("status", dead ? BusMessage.STATUS_DEAD : BusMessage.STATUS_PENDING)
                .set("updatedAt", now)
                .set("lastError", error)
                .unset("lockedUntil")
                .unset("consumer");
        if (!dead) {
            update.set("nextAttemptAt", now.plusSeconds(backoffSeconds(message.getAttempts())));
        }
        mongo.updateFirst(new Query(Criteria.where("_id").is(message.getId())), update, BusMessage.class);
        return dead ? BusMessage.STATUS_DEAD : BusMessage.STATUS_PENDING;
    }

    /** 退避：5s、10s、20s、40s… 最多 5 分钟 */
    private static long backoffSeconds(int attempts) {
        long delay = 5L << Math.min(6, Math.max(0, attempts - 1));
        return Math.min(delay, 300L);
    }

    /**
     * 回收过期租约：attempts 用尽的进死信，其余重新排队。
     *
     * @return {@code [重新排队数, 死信数]}
     */
    public long[] releaseExpiredLeases(Instant now, int maxAttempts) {
        Criteria expired = Criteria.where("status").is(BusMessage.STATUS_PROCESSING)
                .and("lockedUntil").lt(now);

        Query retryQuery = new Query(new Criteria().andOperator(expired,
                Criteria.where("attempts").lt(maxAttempts)));
        Update retryUpdate = new Update()
                .set("status", BusMessage.STATUS_PENDING)
                .set("nextAttemptAt", now)
                .set("updatedAt", now)
                .set("lastError", "租约超时，重新投递")
                .unset("lockedUntil")
                .unset("consumer");
        long retried = mongo.updateMulti(retryQuery, retryUpdate, BusMessage.class).getModifiedCount();

        Query deadQuery = new Query(new Criteria().andOperator(expired,
                Criteria.where("attempts").gte(maxAttempts)));
        Update deadUpdate = new Update()
                .set("status", BusMessage.STATUS_DEAD)
                .set("updatedAt", now)
                .set("lastError", "租约超时且重试次数已用尽")
                .unset("lockedUntil");
        long dead = mongo.updateMulti(deadQuery, deadUpdate, BusMessage.class).getModifiedCount();

        return new long[]{retried, dead};
    }

    /** 队列状态统计（管理页/排障用） */
    public Map<String, Long> counts() {
        Map<String, Long> counts = new LinkedHashMap<>();
        long total = 0;
        for (String status : new String[]{BusMessage.STATUS_PENDING, BusMessage.STATUS_PROCESSING,
                BusMessage.STATUS_DELIVERED, BusMessage.STATUS_DEAD}) {
            long count = mongo.count(new Query(Criteria.where("status").is(status)), BusMessage.class);
            counts.put(status, count);
            total += count;
        }
        counts.put("total", total);
        return counts;
    }
}
