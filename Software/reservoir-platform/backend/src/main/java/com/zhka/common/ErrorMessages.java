package com.zhka.common;

import java.util.concurrent.TimeoutException;

/**
 * 把底层异常（Dify / ASR / 网络）翻译成用户可读提示与业务错误码。
 *
 * <p>注意：{@link #friendly(Throwable)} 与 {@link #errorCode(Throwable)} 的判断顺序
 * 沿用原有实现（前者先判连接、后者先判鉴权），改动顺序会改变最终提示，请勿调换。
 */
public final class ErrorMessages {

    private ErrorMessages() {
    }

    /** 面向用户的友好提示 */
    public static String friendly(Throwable e) {
        String message = lowercaseMessage(e);
        if (message.contains("connection refused") || message.contains("connect")) {
            return "无法连接知识库服务，请确认 Dify 已启动";
        }
        if (message.contains("401") || message.contains("unauthorized")) {
            return "知识库密钥无效，请联系管理员";
        }
        if (message.contains("404")) {
            return "知识库应用不存在，请检查配置";
        }
        if (message.contains("timeout") || e instanceof TimeoutException) {
            return "知识库响应超时，请稍后重试";
        }
        return "知识库服务暂时不可用，请稍后重试";
    }

    /** 异常对应的业务错误码（放在响应体中，HTTP 状态仍为 200） */
    public static int errorCode(Throwable e) {
        String message = lowercaseMessage(e);
        if (message.contains("401") || message.contains("unauthorized")) {
            return 401;
        }
        if (message.contains("404")) {
            return 404;
        }
        if (message.contains("connection refused") || message.contains("connect")) {
            return 502;
        }
        if (message.contains("timeout")) {
            return 504;
        }
        return 500;
    }

    private static String lowercaseMessage(Throwable e) {
        return e.getMessage() == null ? "" : e.getMessage().toLowerCase();
    }
}
