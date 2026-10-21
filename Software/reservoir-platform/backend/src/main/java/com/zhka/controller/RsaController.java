package com.zhka.controller;

import com.zhka.service.RsaKeyService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 下发登录口令加密用的 RSA 公钥：{@code GET /api/get_rsa}（纯文本 Base64）。
 *
 * <p>原类名 {@code RSAController} 不符合驼峰命名规范，已更名。
 */
@RestController
@RequestMapping("/api")
public class RsaController {

    private final RsaKeyService rsaKeyService;

    public RsaController(RsaKeyService rsaKeyService) {
        this.rsaKeyService = rsaKeyService;
    }

    @GetMapping("/get_rsa")
    public String getPublicKey() {
        return rsaKeyService.getPublicKey();
    }
}
