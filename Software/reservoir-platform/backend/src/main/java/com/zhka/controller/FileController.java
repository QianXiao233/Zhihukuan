package com.zhka.controller;

import com.zhka.common.ApiResponse;
import com.zhka.common.ErrorMessages;
import com.zhka.dto.UploadedFileData;
import com.zhka.service.DifyService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import reactor.core.publisher.Mono;

import java.io.IOException;

/**
 * 多模态文件上传。
 *
 * <p>{@code POST /api/files/upload}（multipart/form-data，字段名 file）：
 * 后端转投 Dify 的文件上传接口，把 Dify 返回的 file id 透传给前端，
 * 前端在后续 {@code /api/chat/stream} 中通过 {@code file_ids} 引用这些文件。
 */
@RestController
@RequestMapping("/api/files")
public class FileController {

    private final DifyService difyService;

    public FileController(DifyService difyService) {
        this.difyService = difyService;
    }

    @PostMapping(value = "/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Mono<ApiResponse<UploadedFileData>> upload(@RequestParam("file") MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return Mono.just(ApiResponse.error(400, "上传文件为空"));
        }

        byte[] bytes;
        try {
            bytes = file.getBytes();
        } catch (IOException e) {
            return Mono.just(ApiResponse.error(500, "读取上传文件失败"));
        }

        return difyService.uploadFile(file.getOriginalFilename(), bytes, file.getContentType())
                .map(ApiResponse::ok)
                .onErrorResume(e -> {
                    String reason = ErrorMessages.friendly(e);
                    int code = reason.contains("连接") ? 502 : 500;
                    return Mono.just(ApiResponse.error(code, "文件上传到知识库失败：" + reason));
                });
    }
}
