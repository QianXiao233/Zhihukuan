package com.zhka.dto;

import com.fasterxml.jackson.annotation.JsonInclude;

import java.util.Map;

/** 页面跳转指令（由 Dify 输出解析而来）。 */
@JsonInclude(JsonInclude.Include.NON_NULL)
public record NavigateCommand(
        String action,
        String target,
        Map<String, String> params,
        String reason) {
}
