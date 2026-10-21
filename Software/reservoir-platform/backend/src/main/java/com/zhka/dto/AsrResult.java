package com.zhka.dto;

/** 语音识别结果，对应 {@code {"text": "..."}}。 */
public record AsrResult(String text) {

    public static AsrResult empty() {
        return new AsrResult("");
    }
}
