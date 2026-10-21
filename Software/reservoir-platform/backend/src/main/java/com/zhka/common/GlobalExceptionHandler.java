package com.zhka.common;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.ErrorResponse;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.dao.DataIntegrityViolationException;

/**
 * 全局异常处理：把散落在各 Controller 里的 try/catch 收敛到一处。
 *
 * <p>约定：
 * <ul>
 *   <li>{@link BusinessException} → 用它自带的状态码与提示</li>
 *   <li>Spring 自身的 Web 异常（404 / 405 / 缺参数等，均实现 {@link ErrorResponse}）
 *       → 保留原状态码，只把响应体换成 {@link ApiResponse}</li>
 *   <li>其余未预期异常 → 500，并记录完整堆栈；对外不暴露内部信息</li>
 * </ul>
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BusinessException.class)
    public ResponseEntity<ApiResponse<Void>> handleBusiness(BusinessException e) {
        log.warn("业务异常: {}", e.getMessage());
        HttpStatus status = e.getStatus();
        return ResponseEntity.status(status).body(ApiResponse.error(status.value(), e.getMessage()));
    }

    @ExceptionHandler(DataIntegrityViolationException.class)
    public ResponseEntity<ApiResponse<Void>> handleDataIntegrity(DataIntegrityViolationException e) {
        log.warn("数据库约束校验失败: {}", e.getMostSpecificCause().getMessage());
        String detail = e.getMostSpecificCause().getMessage();
        String message = detail != null && detail.contains("dam_storage")
                ? "总库容数值超出数据库范围，请检查单位或数值"
                : "提交的数据不符合数据库约束，请检查后重试";
        return ResponseEntity.badRequest().body(ApiResponse.error(HttpStatus.BAD_REQUEST.value(), message));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ApiResponse<Void>> handleUnexpected(Exception e) {
        // Spring MVC 自带异常（如 NoResourceFoundException）本身带正确的状态码，
        // 直接转成统一响应体，避免把 404 误报成 500。
        if (e instanceof ErrorResponse errorResponse) {
            int status = errorResponse.getStatusCode().value();
            if (status >= HttpStatus.INTERNAL_SERVER_ERROR.value()) {
                log.error("请求处理失败: {}", e.getMessage(), e);
            }
            String detail = errorResponse.getBody().getDetail();
            String message = detail == null ? errorResponse.getBody().getTitle() : detail;
            return ResponseEntity.status(status).body(ApiResponse.error(status, message));
        }

        log.error("未处理的异常", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(ApiResponse.error(HttpStatus.INTERNAL_SERVER_ERROR.value(), "服务暂时不可用，请稍后重试"));
    }
}
