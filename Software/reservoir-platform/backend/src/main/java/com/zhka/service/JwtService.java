package com.zhka.service;

import com.zhka.config.PlatformProperties;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.security.SecureRandom;
import java.util.Base64;
import java.util.Date;

/** JWT 签发与校验（HS256，密钥来自 {@code reservoir.platform.jwt-secret}）。 */
@Component
public class JwtService {

    private static final Logger log = LoggerFactory.getLogger(JwtService.class);

    /** 过期时间：7 天 */
    private static final long EXPIRE_MILLIS = 7L * 24 * 60 * 60 * 1000;
    private static final int RANDOM_SECRET_BYTES = 48;
    private static final String CLAIM_LEVEL = "level";

    private final Key key;

    public JwtService(PlatformProperties properties) {
        String secret = properties.getJwtSecret() == null ? "" : properties.getJwtSecret().trim();
        if (secret.isEmpty()) {
            // 安全考虑：绝不使用代码里写死的密钥兜底——那等于公开管理权限。
            // 未配置时生成随机密钥，重启后旧令牌失效（需重新登录），仅适合开发/演示。
            byte[] random = new byte[RANDOM_SECRET_BYTES];
            new SecureRandom().nextBytes(random);
            secret = Base64.getEncoder().encodeToString(random);
            log.warn("[JWT] 未配置 JWT_SECRET，已生成随机密钥。"
                    + "重启后端会使已签发的令牌失效；生产环境请通过环境变量或 backend/.env 配置固定密钥。");
        }
        this.key = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    public String generateToken(String username, Integer level) {
        return Jwts.builder()
                .setSubject(username)
                .claim(CLAIM_LEVEL, level)
                .setIssuedAt(new Date())
                .setExpiration(new Date(System.currentTimeMillis() + EXPIRE_MILLIS))
                .signWith(key)
                .compact();
    }

    public boolean isValid(String token) {
        try {
            parse(token);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    public String getUsername(String token) {
        return parse(token).getSubject();
    }

    public Integer getLevel(String token) {
        Object level = parse(token).get(CLAIM_LEVEL);
        return level instanceof Number number ? number.intValue() : null;
    }

    private Claims parse(String token) {
        return Jwts.parserBuilder()
                .setSigningKey(key)
                .build()
                .parseClaimsJws(token)
                .getBody();
    }
}
