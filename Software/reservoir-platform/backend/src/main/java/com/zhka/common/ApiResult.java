package com.zhka.common;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 平台管理类接口的历史响应契约：{@code {success, message, data?, username?, level?}}。
 *
 * <p>管理端前端已经按该结构实现（判断 {@code success} 而不是 {@code code}），
 * 因此平台接口继续沿用，未强行统一到 {@link ApiResponse}。
 * 用在 Controller 中替代零散的 {@code HashMap} 拼装。
 */
public final class ApiResult {

    private static final String SUCCESS = "success";
    private static final String MESSAGE = "message";
    private static final String DATA = "data";
    private static final String USERNAME = "username";
    private static final String LEVEL = "level";

    private final Map<String, Object> body = new LinkedHashMap<>();

    private ApiResult(boolean success, String message) {
        body.put(SUCCESS, success);
        if (message != null) {
            body.put(MESSAGE, message);
        }
    }

    /** 成功，且不回传 message */
    public static ApiResult success() {
        return new ApiResult(true, null);
    }

    /** 成功，并带上提示语 */
    public static ApiResult success(String message) {
        return new ApiResult(true, message);
    }

    /** 失败 */
    public static ApiResult failure(String message) {
        return new ApiResult(false, message);
    }

    /** 回传当前登录身份，保持与原接口一致的响应字段 */
    public ApiResult withUser(String username, Integer level) {
        return with(USERNAME, username).with(LEVEL, level);
    }

    /** 挂载业务数据 */
    public ApiResult data(Object data) {
        return with(DATA, data);
    }

    /** 追加任意字段 */
    public ApiResult with(String key, Object value) {
        body.put(key, value);
        return this;
    }

    public Map<String, Object> toMap() {
        return body;
    }
}
