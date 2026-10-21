package com.zhka.controller;

import com.zhka.common.ApiResult;
import com.zhka.service.AuthService;

import java.util.Map;

/**
 * 平台管理接口的公共支撑。
 *
 * <p>统一处理两件事：解析 {@code Authorization: Bearer <token>}、拼装
 * {@code {success,message,data,username,level}} 的历史响应结构。
 * 凭证无效时仍返回 HTTP 200 + {@code success:false}（管理端前端按该契约判断）。
 */
abstract class AbstractManageController {

    protected static final String TOKEN_INVALID_MESSAGE = "凭证验证失败!";

    protected final AuthService authService;

    protected AbstractManageController(AuthService authService) {
        this.authService = authService;
    }

    /** 解析当前登录身份；返回 null 表示凭证无效 */
    protected AuthService.AuthUser currentUser(String authorization) {
        return authService.verify(authorization);
    }

    protected Map<String, Object> tokenInvalid() {
        return ApiResult.failure(TOKEN_INVALID_MESSAGE).toMap();
    }

    /** 成功 + 回传身份，不带提示语（对应原 list 类接口） */
    protected Map<String, Object> okWithData(AuthService.AuthUser user, Object data) {
        return ApiResult.success().withUser(user.username(), user.level()).data(data).toMap();
    }

    /** 成功 + 提示语（对应原 add / update / delete） */
    protected Map<String, Object> ok(AuthService.AuthUser user, String message) {
        return ApiResult.success(message).withUser(user.username(), user.level()).toMap();
    }

    /** 业务失败：与原实现一致，失败响应同样回传身份 */
    protected Map<String, Object> fail(AuthService.AuthUser user, String message) {
        return ApiResult.failure(message).withUser(user.username(), user.level()).toMap();
    }
}
