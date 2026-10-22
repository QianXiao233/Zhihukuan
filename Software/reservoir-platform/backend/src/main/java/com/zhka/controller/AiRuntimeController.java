package com.zhka.controller;

import com.zhka.common.ApiResponse;
import com.zhka.common.BusinessException;
import com.zhka.service.AuthService;
import com.zhka.service.PlatformRuntimeService;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * AI 运行数据接口：给调试、前端状态展示或后续 Dify 工具调用使用。
 *
 * <p>和对话上下文用的是同一份 {@link PlatformRuntimeService#snapshot()}，
 * 保证接口看到的数据与 AI 看到的一致。
 */
@RestController
@RequestMapping("/api/ai")
public class AiRuntimeController {

    private final PlatformRuntimeService runtime;
    private final AuthService authService;

    public AiRuntimeController(PlatformRuntimeService runtime, AuthService authService) {
        this.runtime = runtime;
        this.authService = authService;
    }

    @GetMapping("/runtime")
    public ApiResponse<Map<String, Object>> runtime(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        if (authService.verify(authorization) == null) {
            throw new BusinessException("登录已失效，请重新登录", HttpStatus.UNAUTHORIZED);
        }
        return ApiResponse.ok(runtime.snapshot());
    }
}
