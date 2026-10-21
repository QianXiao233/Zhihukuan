package com.zhka.controller;

import com.zhka.common.BusinessException;
import com.zhka.dto.AsrResult;
import com.zhka.service.AsrService;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import reactor.core.publisher.Mono;

import java.io.IOException;

/**
 * 语音识别：{@code POST /api/asr}（multipart/form-data，字段名 file）。
 *
 * <p>前端录音（WAV 16kHz 单声道）后上传，返回 {@code {"text": "..."}}。
 */
@RestController
@RequestMapping("/api")
public class AsrController {

    private final AsrService asrService;

    public AsrController(AsrService asrService) {
        this.asrService = asrService;
    }

    @PostMapping(value = "/asr", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Mono<AsrResult> recognize(@RequestParam("file") MultipartFile file) {
        if (file == null || file.isEmpty()) {
            return Mono.just(AsrResult.empty());
        }
        if (!asrService.isEnabled()) {
            return Mono.error(new BusinessException("语音识别功能未启用"));
        }

        byte[] bytes;
        try {
            bytes = file.getBytes();
        } catch (IOException e) {
            return Mono.error(new BusinessException("读取音频文件失败"));
        }

        // 识别失败时返回空文本，前端按「没听到」处理，不打断整轮对话
        return asrService.recognize(bytes, file.getOriginalFilename())
                .map(AsrResult::new)
                .onErrorResume(e -> Mono.just(AsrResult.empty()));
    }
}
