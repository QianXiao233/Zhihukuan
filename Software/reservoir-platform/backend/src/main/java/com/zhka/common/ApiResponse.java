package com.zhka.common;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * 统一响应包装。
 *
 * <p>{@code code} 为 0 表示成功，其余为业务错误码；{@code data} 为空时不参与序列化。
 * 问答、文件上传等前端契约均基于该结构（对应前端 {@code ApiResponse} 类型）。
 *
 * @param <T> 业务数据类型
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record ApiResponse<T>(int code, String message, T data) {

    /** 成功响应 */
    public static <T> ApiResponse<T> ok(T data) {
        return new ApiResponse<>(0, "success", data);
    }

    /** 失败响应：code 由调用方按业务约定给出 */
    public static <T> ApiResponse<T> error(int code, String message) {
        return new ApiResponse<>(code, message, null);
    }
}
