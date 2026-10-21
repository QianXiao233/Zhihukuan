package com.zhka.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

/** 健康检查结果。 */
public record HealthData(
        String status,
        @JsonProperty("dify_api_base") String difyApiBase,
        @JsonProperty("dify_key_configured") boolean difyKeyConfigured,
        @JsonProperty("asr_available") boolean asrAvailable,
        @JsonProperty("tts_provider") String ttsProvider) {
}
