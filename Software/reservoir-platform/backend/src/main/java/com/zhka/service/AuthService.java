package com.zhka.service;

import com.zhka.entity.User;
import com.zhka.mapper.UserMapper;
import com.zhka.util.RsaUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 登录鉴权用例：RSA 解密口令 → 校验用户 → 签发 / 校验 JWT。
 *
 * <p>把原本堆在 Controller 里的加解密、查库、异常兜底收敛到此处。
 */
@Service
public class AuthService {

    private static final Logger log = LoggerFactory.getLogger(AuthService.class);

    private static final String BEARER_PREFIX = "Bearer ";

    private final UserMapper userMapper;
    private final JwtService jwtService;
    private final RsaKeyService rsaKeyService;

    public AuthService(UserMapper userMapper, JwtService jwtService, RsaKeyService rsaKeyService) {
        this.userMapper = userMapper;
        this.jwtService = jwtService;
        this.rsaKeyService = rsaKeyService;
    }

    /** 已登录身份 */
    public record AuthUser(String username, Integer level) {
    }

    /** 登录结果（保持原有 {success, message, token} 契约） */
    public record LoginResult(boolean success, String message, String token) {

        static LoginResult success(String token) {
            return new LoginResult(true, "登录成功", token);
        }

        static LoginResult failure(String message) {
            return new LoginResult(false, message, null);
        }
    }

    /** 注册结果 */
    public record RegisterResult(boolean success, String message) {

        static RegisterResult success(String message) {
            return new RegisterResult(true, message);
        }

        static RegisterResult failure(String message) {
            return new RegisterResult(false, message);
        }
    }

    /**
     * 解析 {@code Authorization: Bearer <token>}。
     *
     * @return 凭证无效时返回 null
     */
    public AuthUser verify(String authorizationHeader) {
        if (authorizationHeader == null || !authorizationHeader.startsWith(BEARER_PREFIX)) {
            return null;
        }
        return validate(authorizationHeader.substring(BEARER_PREFIX.length()));
    }

    /** 直接校验令牌文本 */
    public AuthUser validate(String token) {
        if (token == null || !jwtService.isValid(token)) {
            return null;
        }
        User user = userMapper.findByUsername(jwtService.getUsername(token));
        return user == null ? null : new AuthUser(user.getUsername(), user.getLevel());
    }

    /**
     * 登录：前端用公钥加密口令后提交，此处解密再比对。
     *
     * <p>查询与解密过程中的异常统一按「登录失败」返回，避免向前端泄漏内部错误。
     */
    public LoginResult login(String username, String encryptedPassword) {
        try {
            String password = RsaUtils.decrypt(encryptedPassword, rsaKeyService.getPrivateKey());
            User user = userMapper.findByUsername(username);
            if (user == null || !password.equals(user.getPassword())) {
                return LoginResult.failure("用户名或密码错误");
            }
            return LoginResult.success(jwtService.generateToken(username, user.getLevel()));
        } catch (Exception e) {
            log.warn("登录失败（口令解密或用户查询异常）username={}: {}", username, e.getMessage());
            return LoginResult.failure("登录失败，请重试");
        }
    }

    /** 注册：与登录保持同一契约（前端传密文，后端解密后存明文） */
    public RegisterResult register(String username, String encryptedPassword, Integer level) {
        try {
            String password = RsaUtils.decrypt(encryptedPassword, rsaKeyService.getPrivateKey());
            if (userMapper.findByUsername(username) != null) {
                return RegisterResult.failure("用户已存在");
            }
            User user = new User();
            user.setUsername(username);
            user.setPassword(password);
            user.setLevel(level);
            userMapper.insert(user);
            return RegisterResult.success("注册成功！");
        } catch (Exception e) {
            log.error("注册失败 username={}", username, e);
            return RegisterResult.failure("发生未知错误，服务不可用，请联系后端服务人员");
        }
    }
}
