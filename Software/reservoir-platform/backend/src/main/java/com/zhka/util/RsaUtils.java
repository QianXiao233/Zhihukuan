package com.zhka.util;

import javax.crypto.Cipher;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.PublicKey;
import java.security.spec.PKCS8EncodedKeySpec;
import java.security.spec.X509EncodedKeySpec;
import java.util.Base64;

/**
 * RSA 加解密工具（登录口令在前端用公钥加密，后端用私钥还原）。
 *
 * <p>原类名为 {@code RsaService} 但实际是无状态静态工具，已更名并移入 util 包。
 */
public final class RsaUtils {

    private static final String ALGORITHM = "RSA";
    private static final int KEY_SIZE = 2048;

    private RsaUtils() {
    }

    /** 生成 2048 位密钥对 */
    public static KeyPair generateKeyPair() throws Exception {
        KeyPairGenerator generator = KeyPairGenerator.getInstance(ALGORITHM);
        generator.initialize(KEY_SIZE);
        return generator.generateKeyPair();
    }

    /** 公钥加密，返回 Base64 */
    public static String encrypt(String data, PublicKey publicKey) throws Exception {
        Cipher cipher = Cipher.getInstance(ALGORITHM);
        cipher.init(Cipher.ENCRYPT_MODE, publicKey);
        byte[] encrypted = cipher.doFinal(data.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(encrypted);
    }

    /** 私钥解密 */
    public static String decrypt(String encryptedData, PrivateKey privateKey) throws Exception {
        byte[] encrypted = Base64.getDecoder().decode(encryptedData);
        Cipher cipher = Cipher.getInstance(ALGORITHM);
        cipher.init(Cipher.DECRYPT_MODE, privateKey);
        return new String(cipher.doFinal(encrypted), StandardCharsets.UTF_8);
    }

    /** 公钥 → Base64（下发给前端） */
    public static String toBase64(PublicKey publicKey) {
        return Base64.getEncoder().encodeToString(publicKey.getEncoded());
    }

    /** Base64 → 公钥 */
    public static PublicKey publicKeyFromBase64(String key) throws Exception {
        byte[] keyBytes = Base64.getDecoder().decode(key);
        return KeyFactory.getInstance(ALGORITHM).generatePublic(new X509EncodedKeySpec(keyBytes));
    }

    /** Base64 → 私钥 */
    public static PrivateKey privateKeyFromBase64(String key) throws Exception {
        byte[] keyBytes = Base64.getDecoder().decode(key);
        return KeyFactory.getInstance(ALGORITHM).generatePrivate(new PKCS8EncodedKeySpec(keyBytes));
    }
}
