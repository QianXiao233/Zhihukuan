package com.zhka.config;

import com.zhka.service.BusTicketService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

/**
 * SSE 订阅入口的票据校验。
 *
 * <p>只拦截 {@code /api/bus/subscribe}：一次性票据换连接，票据无效直接返回 401 JSON，
 * 避免把校验失败变成“HTTP 200 但连接立刻断开”这种难排查的状态。
 * 浏览器只允许订阅 {@code ui.*} 频道，避免把服务间的业务消息推到页面。
 */
@Component
public class BusSseAuthFilter extends OncePerRequestFilter {

    public static final String USER_ATTRIBUTE = "bus.sse.username";

    private final BusTicketService tickets;

    public BusSseAuthFilter(BusTicketService tickets) {
        this.tickets = tickets;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !"/api/bus/subscribe".equals(request.getRequestURI());
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        BusTicketService.Ticket ticket = tickets.consume(request.getParameter("ticket"));
        if (ticket == null) {
            writeJson(response, HttpServletResponse.SC_UNAUTHORIZED, "订阅票据无效或已过期，请重新获取");
            return;
        }
        String topic = request.getParameter("topic");
        if (topic == null || topic.isBlank()) {
            topic = "ui.#";
        }
        if (!topic.startsWith("ui.")) {
            writeJson(response, HttpServletResponse.SC_FORBIDDEN, "浏览器只能订阅 ui.* 频道");
            return;
        }
        request.setAttribute(USER_ATTRIBUTE, ticket.username());
        chain.doFilter(request, response);
    }

    private static void writeJson(HttpServletResponse response, int status, String message) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"code\":" + status + ",\"message\":\"" + message + "\"}");
    }
}
