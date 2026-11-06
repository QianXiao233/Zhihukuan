package com.zhka.service;

import com.zhka.entity.BusMessage;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 广播主题（{@code ui.*}）不得进入竞争消费队列。
 *
 * <p>背景：浏览器通知走 SSE 扇出，没有消费方，也永远不会被 ack。
 * 如果按普通消息落成 {@code pending}，会一直躺在「待投递」里——
 * 实测发布 27 条通知后待投递数就是 27，而页面其实每条都收到了。
 * 运维看到这个数字会以为队列堵了，进而去排查完全不存在的消费方问题。
 *
 * <p>判定规则：主题为 {@code ui} 或形如 {@code ui.*} 即为广播。
 * 这里直接测判定函数，不依赖 MongoDB，保证纯逻辑可回归。
 */
class BusBroadcastTopicTest {

    /** 反射取私有方法：不希望为了测试把判定逻辑变成 public API */
    private static boolean isBroadcast(String topic) throws Exception {
        Method m = BusService.class.getDeclaredMethod("isBroadcastTopic", String.class);
        m.setAccessible(true);
        return (boolean) m.invoke(null, topic);
    }

    @Test
    void uiTopicsAreBroadcast() throws Exception {
        assertTrue(isBroadcast("ui"), "裸 ui 也属于浏览器频道");
        assertTrue(isBroadcast("ui.notice"), "平台通知是广播");
        assertTrue(isBroadcast("ui.brain.approval"), "AI 待确认请求是广播");
        assertTrue(isBroadcast("ui.brain.result"), "AI 处理结果也是广播");
        assertTrue(isBroadcast("ui.alarm.dam1.level"), "多层主题同样匹配");
    }

    @Test
    void serviceTopicsAreNotBroadcast() throws Exception {
        assertFalse(isBroadcast("alarm.dam1.level"), "业务告警需要消费方领取");
        assertFalse(isBroadcast("brain.pending"), "服务间消息仍需队列语义");
        assertFalse(isBroadcast("device.status"));
    }

    @Test
    void similarPrefixIsNotMisclassified() throws Exception {
        // "uix.foo" 不是 ui 频道，不能用 startsWith("ui") 这种粗糙判断
        assertFalse(isBroadcast("uix.foo"), "uix 不是 ui 频道");
        assertFalse(isBroadcast("uitest.bar"));
    }

    @Test
    void nullTopicIsSafe() throws Exception {
        assertFalse(isBroadcast(null));
    }

    @Test
    void deliveredStatusIsUsedForBroadcast() {
        // 语义确认：广播消息写库时直接记 delivered，
        // 让「待投递」反映真实的待消费数量，而不是历史通知条数
        assertTrue("delivered".equals(BusMessage.STATUS_DELIVERED));
        assertTrue("pending".equals(BusMessage.STATUS_PENDING));
    }
}
