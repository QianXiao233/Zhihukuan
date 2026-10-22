package com.zhka.service;

import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 浏览器 SSE 订阅票据：登录用户先换一次性票据，再用票据连 SSE。
 *
 * <p>为什么不直接把 JWT 放 URL：{@code EventSource} 不能自定义请求头，
 * JWT 进查询串会被 Nginx / 网关的访问日志记录下来。票据 60 秒有效、只能用一次，
 * 即使被记进日志也没有再利用价值。
 */
@Service
public class BusTicketService {

    private static final long TTL_SECONDS = 60;
    private static final int MAX_PENDING = 2048;

    private final Map<String, Ticket> tickets = new ConcurrentHashMap<>();

    /** 票据内容：谁订阅、订阅什么主题 */
    public record Ticket(String username, int level, String topics, Instant expiresAt) {
    }

    public String issue(AuthService.AuthUser user, String topics) {
        purgeExpired();
        // 防止被刷爆内存：票据只保留很短时间，超过上限就丢掉最早的一批
        if (tickets.size() >= MAX_PENDING) {
            tickets.clear();
        }
        String id = UUID.randomUUID().toString().replace("-", "");
        tickets.put(id, new Ticket(user.username(), user.level(), topics,
                Instant.now().plusSeconds(TTL_SECONDS)));
        return id;
    }

    /** 消费票据；无效或过期返回 null（一次性，消费即删除） */
    public Ticket consume(String id) {
        if (id == null || id.isBlank()) {
            return null;
        }
        Ticket ticket = tickets.remove(id);
        if (ticket == null || ticket.expiresAt().isBefore(Instant.now())) {
            return null;
        }
        return ticket;
    }

    public int pendingCount() {
        purgeExpired();
        return tickets.size();
    }

    private void purgeExpired() {
        Instant now = Instant.now();
        tickets.entrySet().removeIf(entry -> entry.getValue().expiresAt().isBefore(now));
    }
}
