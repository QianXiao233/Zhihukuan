package com.zhka.controller;

import com.zhka.common.ApiResult;
import com.zhka.entity.BusMessage;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.query.Criteria;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 数字孪生标签状态：读取服务总线里最新的溺水 / 无人艇消息。
 *
 * <p>浏览器只订阅 {@code ui.*}，不能直接拉 {@code alarm.*} 服务消息，所以这里由后端
 * 只读查询 {@code bus_messages} 的最新一条，前端轮询展示状态灯。不会领取 / 消费消息，
 * 不影响真正的业务消费者。
 */
@RestController
@RequestMapping("/api/twin")
public class TwinAlertController {

    private final MongoTemplate mongo;

    public TwinAlertController(MongoTemplate mongo) {
        this.mongo = mongo;
    }

    @GetMapping("/alerts")
    public Map<String, Object> alerts() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("drowning", latest("alarm.drowning"));
        data.put("boat", latest("alarm.boat"));
        return ApiResult.success().data(data).toMap();
    }

    private Map<String, Object> latest(String topic) {
        try {
            Query query = new Query(Criteria.where("topic").is(topic))
                    .with(Sort.by(Sort.Direction.DESC, "createdAt"))
                    .limit(1);
            BusMessage message = mongo.findOne(query, BusMessage.class);
            if (message == null) {
                return null;
            }
            Map<String, Object> payload = message.getPayload() == null ? Map.of() : message.getPayload();
            String status = text(payload.get("status"));
            String detail = text(payload.get("detail"));
            if (detail.isEmpty()) {
                detail = text(payload.get("message"));
            }
            if (detail.isEmpty()) {
                detail = text(payload.get("description"));
            }
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("status", status.isEmpty() ? "Normal" : status);
            row.put("detail", detail);
            row.put("time", message.getCreatedAt());
            row.put("msgId", message.getMsgId());
            return row;
        } catch (Exception ex) {
            return null;
        }
    }

    private static String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }
}
