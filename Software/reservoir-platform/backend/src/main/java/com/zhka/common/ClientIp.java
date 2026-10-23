package com.zhka.common;

import jakarta.servlet.http.HttpServletRequest;

/**
 * 解析客户端真实 IP。
 *
 * <p>反向代理之后 {@code getRemoteAddr()} 拿到的是代理地址（通常就是 127.0.0.1），
 * 真实来源在转发头里。取值顺序：
 *
 * <ol>
 *   <li>{@code X-Forwarded-For}：可能是 {@code "client, proxy1, proxy2"}，取最左的客户端值；
 *   <li>{@code X-Real-IP}：nginx 直接写入的单个地址；
 *   <li>{@code getRemoteAddr()}：没有经过代理时的直连地址。
 * </ol>
 *
 * <p>{@code X-Forwarded-For} 可被伪造，只有在可信代理后面才应信任。因此后端应只监听回环地址、
 * 由代理独占对外入口，否则任何人都能随意伪造来源 IP。
 */
public final class ClientIp {

    /** IPv6 回环地址统一写成 127.0.0.1，便于阅读和统计。 */
    private static final String IPV6_LOOPBACK = "0:0:0:0:0:0:0:1";

    private ClientIp() {
    }

    /** 返回可入库的客户端 IP；取不到时返回空串，绝不返回 null。 */
    public static String resolve(HttpServletRequest request) {
        if (request == null) {
            return "";
        }
        String ip = request.getHeader("X-Forwarded-For");
        if (isBlank(ip)) {
            ip = request.getHeader("X-Real-IP");
        }
        if (isBlank(ip)) {
            ip = request.getRemoteAddr();
        }
        if (isBlank(ip)) {
            return "";
        }
        // "client, proxy1, proxy2" → 只保留最左的客户端地址
        int comma = ip.indexOf(',');
        if (comma > 0) {
            ip = ip.substring(0, comma);
        }
        ip = ip.trim();
        if (IPV6_LOOPBACK.equals(ip)) {
            ip = "127.0.0.1";
        }
        return ip;
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank() || "unknown".equalsIgnoreCase(value.trim());
    }
}
