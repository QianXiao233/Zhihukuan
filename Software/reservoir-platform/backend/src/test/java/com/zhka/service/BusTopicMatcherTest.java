package com.zhka.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/** 主题通配规则：* 一层、# 任意层，发布主题必须具体。 */
class BusTopicMatcherTest {

    @Test
    void validatesConcreteTopics() {
        assertTrue(BusTopicMatcher.isValidTopic("alarm.dam1.level"));
        assertTrue(BusTopicMatcher.isValidTopic("alarm"));
        assertTrue(BusTopicMatcher.isValidTopic("alarm.dam-1.water_level"));
        assertFalse(BusTopicMatcher.isValidTopic("alarm.*"));
        assertFalse(BusTopicMatcher.isValidTopic("alarm.#"));
        assertFalse(BusTopicMatcher.isValidTopic("alarm..level"));
        assertFalse(BusTopicMatcher.isValidTopic(""));
        assertFalse(BusTopicMatcher.isValidTopic(null));
    }

    @Test
    void starMatchesExactlyOneLevel() {
        assertTrue(BusTopicMatcher.matchesAny("alarm.dam1", "alarm.*"));
        assertFalse(BusTopicMatcher.matchesAny("alarm.dam1.level", "alarm.*"));
        assertTrue(BusTopicMatcher.matchesAny("alarm.dam1", "alarm.dam1"));
        assertFalse(BusTopicMatcher.matchesAny("alarm.dam2", "alarm.dam1"));
    }

    @Test
    void hashMatchesAnySuffix() {
        assertTrue(BusTopicMatcher.matchesAny("alarm.dam1.level", "alarm.#"));
        assertTrue(BusTopicMatcher.matchesAny("alarm", "#"));
        assertTrue(BusTopicMatcher.matchesAny("device.boat.moved", "device.#,alarm.#"));
        assertFalse(BusTopicMatcher.matchesAny("other.topic", "alarm.#"));
    }

    @Test
    void regexCoversAllReturnsNull() {
        assertNull(BusTopicMatcher.toRegex("#"));
        assertNull(BusTopicMatcher.toRegex("alarm.#,#"));
        assertTrue(BusTopicMatcher.coversAll("alarm.*,#"));
        assertFalse(BusTopicMatcher.coversAll("alarm.*"));
    }

    @Test
    void regexMatchesSameAsJavaMatcher() {
        String regex = BusTopicMatcher.toRegex("alarm.*,device.#");
        assertTrue(java.util.regex.Pattern.matches(regex, "alarm.dam1"));
        assertFalse(java.util.regex.Pattern.matches(regex, "alarm.dam1.level"));
        assertTrue(java.util.regex.Pattern.matches(regex, "device.boat.moved"));
        assertFalse(java.util.regex.Pattern.matches(regex, "other.topic"));
        assertEquals("(?!)", BusTopicMatcher.toRegex(""));
    }
}
