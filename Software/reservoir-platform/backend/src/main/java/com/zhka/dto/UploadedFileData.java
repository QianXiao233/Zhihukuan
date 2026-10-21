package com.zhka.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 文件上传结果：{@code id} 与 {@code dify_file_id} 目前同值，前端取其一即可。 */
public record UploadedFileData(
        String id,
        String name,
        long size,
        @JsonProperty("mime_type") String mimeType,
        @JsonProperty("dify_file_id") String difyFileId,
        String url) {
}
