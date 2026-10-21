package com.zhka.common;

import org.springframework.http.HttpStatus;

/**
 * 业务异常：携带对外可见的提示与 HTTP 状态码，由 {@link GlobalExceptionHandler} 统一转为响应。
 *
 * <p>只用于「确实需要以错误状态码结束请求」的场景；平台管理类接口沿用
 * {@code 200 + success:false} 的历史契约，请直接返回 {@link ApiResult}，不要抛本异常。
 */
public class BusinessException extends RuntimeException {

    private final HttpStatus status;

    public BusinessException(String message) {
        this(message, HttpStatus.INTERNAL_SERVER_ERROR);
    }

    public BusinessException(String message, HttpStatus status) {
        super(message);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}
