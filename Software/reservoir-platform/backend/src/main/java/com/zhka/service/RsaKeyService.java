package com.zhka.service;

import com.zhka.util.RsaUtils;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.security.KeyPair;
import java.security.PrivateKey;

/**
 * 持有登录口令加解密所需的 RSA 密钥对（启动时生成）。
 *
 * <p>原类名 {@code KeyService} 语义过于宽泛，已更名；静态算法实现见 {@link RsaUtils}。
 * 生产环境应改为从密钥库加载固定密钥，否则重启后前端缓存的老公钥会失效。
 */
@Service
public class RsaKeyService {

    private static final Logger log = LoggerFactory.getLogger(RsaKeyService.class);

    private String publicKey;
    private PrivateKey privateKey;

    @PostConstruct
    public void init() throws Exception {
        KeyPair keyPair = RsaUtils.generateKeyPair();
        this.publicKey = RsaUtils.toBase64(keyPair.getPublic());
        this.privateKey = keyPair.getPrivate();
        log.info("RSA 密钥对已生成（{} 位）", 2048);
    }

    /** 下发给前端的 Base64 公钥 */
    public String getPublicKey() {
        return publicKey;
    }

    public PrivateKey getPrivateKey() {
        return privateKey;
    }
}
