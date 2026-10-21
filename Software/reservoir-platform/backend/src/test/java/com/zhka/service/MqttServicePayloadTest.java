package com.zhka.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONObject;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

/**
 * RTU 报文里的“空值”必须解析成缺测（null），不能变成 0。
 *
 * <p>现场 RTU 会间歇性发 {@code "level":null}；用 fastjson 的
 * {@code getDoubleValue()} 读会得到 0，最终表现为水位 0.00 并误触发下限告警。
 */
class MqttServicePayloadTest {

    private static JSONObject json(String text) {
        return JSON.parseObject(text);
    }

    @Test
    void jsonNullBecomesNull() {
        assertNull(MqttService.doubleValue(json("{\"level\":null}"), "level"));
        assertNull(MqttService.doubleValue(json("{\"temp\":null,\"level\":null,\"ph\":null,\"orp\":null}"), "temp"));
    }

    @Test
    void missingKeyBecomesNull() {
        assertNull(MqttService.doubleValue(json("{\"temp\":25.9}"), "level"));
    }

    @Test
    void emptyOrBlankStringBecomesNull() {
        assertNull(MqttService.doubleValue(json("{\"level\":\"\"}"), "level"));
        assertNull(MqttService.doubleValue(json("{\"level\":\"  \"}"), "level"));
        assertNull(MqttService.doubleValue(json("{\"level\":\"abc\"}"), "level"));
    }

    @Test
    void realZeroIsStillZero() {
        assertEquals(0.0, MqttService.doubleValue(json("{\"level\":0}"), "level"));
        assertEquals(0.0, MqttService.doubleValue(json("{\"level\":\"0\"}"), "level"));
    }

    @Test
    void normalNumbersParse() {
        assertEquals(0.3, MqttService.doubleValue(json("{\"level\":0.3}"), "level"), 1e-9);
        assertEquals(26.1, MqttService.doubleValue(json("{\"level\":\"26.1\"}"), "level"), 1e-9);
    }

    @Test
    void booleanAndObjectAreNotNumbers() {
        assertNull(MqttService.doubleValue(json("{\"level\":true}"), "level"));
        assertNull(MqttService.doubleValue(json("{\"level\":{}}"), "level"));
    }
}
