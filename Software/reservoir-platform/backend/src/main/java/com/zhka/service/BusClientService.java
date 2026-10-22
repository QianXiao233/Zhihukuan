package com.zhka.service;

import com.zhka.common.BusinessException;
import com.zhka.entity.BusClient;
import com.zhka.mapper.BusClientMapper;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.Base64;
import java.util.HexFormat;
import java.util.List;
import java.util.regex.Pattern;

/**
 * 总线客户端（服务身份）管理。
 *
 * <p>密钥只在校验时哈希比对，数据库里存 SHA-256，明文只在创建/轮换时返回一次。
 * 服务调用 {@code /api/bus/**} 时用 {@code Authorization: Bearer <clientId>.<secret>}。
 */
@Service
public class BusClientService {

    private static final Pattern CLIENT_ID = Pattern.compile("^[A-Za-z0-9_-]{2,64}$");
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final int SECRET_BYTES = 24;

    private final BusClientMapper mapper;

    public BusClientService(BusClientMapper mapper) {
        this.mapper = mapper;
    }

    /** 客户端视图（不含密钥哈希） */
    public record BusClientView(String clientId, String clientName, String allowPublish,
                                String allowSubscribe, boolean enabled, LocalDateTime createdAt) {

        static BusClientView from(BusClient client) {
            return new BusClientView(client.getClientId(), client.getClientName(),
                    client.getAllowPublish(), client.getAllowSubscribe(), client.isEnabled(),
                    client.getCreatedAt());
        }
    }

    /** 创建结果：明文密钥只在这里出现一次 */
    public record CreatedClient(BusClientView client, String secret) {
    }

    public CreatedClient create(String clientId, String clientName, String allowPublish, String allowSubscribe) {
        String id = clientId == null ? "" : clientId.trim();
        if (!CLIENT_ID.matcher(id).matches()) {
            throw new BusinessException("client_id 只能是 2~64 位字母、数字、下划线或短横线", HttpStatus.BAD_REQUEST);
        }
        if (mapper.findById(id) != null) {
            throw new BusinessException("client_id 已存在：" + id, HttpStatus.CONFLICT);
        }
        String secret = randomSecret();
        BusClient client = new BusClient();
        client.setClientId(id);
        client.setClientName(clientName == null || clientName.isBlank() ? id : clientName.trim());
        client.setSecretHash(hash(secret));
        client.setAllowPublish(normalizePatterns(allowPublish, "#"));
        client.setAllowSubscribe(normalizePatterns(allowSubscribe, "#"));
        client.setEnabled(true);
        mapper.insert(client);
        return new CreatedClient(BusClientView.from(mapper.findById(id)), secret);
    }

    public List<BusClientView> list() {
        return mapper.findAll().stream().map(BusClientView::from).toList();
    }

    /** 客户端是否存在且启用（发布时校验 target 用） */
    public boolean isEnabled(String clientId) {
        BusClient client = mapper.findById(clientId);
        return client != null && client.isEnabled();
    }

    public boolean setEnabled(String clientId, boolean enabled) {
        return mapper.updateEnabled(clientId, enabled) > 0;
    }

    /** 删除客户端；它已发布/待投递的消息不受影响，按 TTL 自然过期 */
    public boolean delete(String clientId) {
        return mapper.delete(clientId) > 0;
    }

    /** 轮换密钥，旧密钥立即失效 */
    public String rotate(String clientId) {
        BusClient client = mapper.findById(clientId);
        if (client == null) {
            throw new BusinessException("客户端不存在：" + clientId, HttpStatus.NOT_FOUND);
        }
        String secret = randomSecret();
        mapper.updateSecret(clientId, hash(secret));
        return secret;
    }

    /**
     * 校验 {@code Authorization: Bearer <clientId>.<secret>}。
     *
     * @return 校验失败、客户端不存在或被停用时返回 null
     */
    public BusClient authenticate(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return null;
        }
        String token = authorization.substring("Bearer ".length()).trim();
        int separator = token.indexOf('.');
        if (separator <= 0 || separator == token.length() - 1) {
            return null;
        }
        String clientId = token.substring(0, separator);
        String secret = token.substring(separator + 1);
        BusClient client = mapper.findById(clientId);
        if (client == null || !client.isEnabled() || client.getSecretHash() == null) {
            return null;
        }
        byte[] expected = client.getSecretHash().getBytes(StandardCharsets.UTF_8);
        byte[] actual = hash(secret).getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(expected, actual) ? client : null;
    }

    private static String normalizePatterns(String patterns, String fallback) {
        if (patterns == null || patterns.isBlank()) {
            return fallback;
        }
        return patterns.trim();
    }

    private static String randomSecret() {
        byte[] bytes = new byte[SECRET_BYTES];
        RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String hash(String secret) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(secret.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception e) {
            throw new IllegalStateException("SHA-256 不可用", e);
        }
    }
}
