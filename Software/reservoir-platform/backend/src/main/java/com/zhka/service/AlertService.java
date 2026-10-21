package com.zhka.service;

import com.zhka.entity.AlertEvent;
import com.zhka.mapper.AlertEventMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 告警记录读写（MySQL 表 {@code alert_event}）。
 *
 * <p>MySQL 不可用时只记日志并返回空列表：告警记录是辅助信息，
 * 不能因为它把 MQTT 采集线程或管理页带崩。
 */
@Service
public class AlertService {

    private static final Logger log = LoggerFactory.getLogger(AlertService.class);

    private final AlertEventMapper mapper;

    public AlertService(AlertEventMapper mapper) {
        this.mapper = mapper;
    }

    public void record(AlertEvent event) {
        if (event == null) {
            return;
        }
        try {
            mapper.insert(event);
        } catch (Exception e) {
            log.warn("[告警] 告警记录写入 MySQL 失败: {}", e.getMessage());
        }
    }

    public List<AlertEvent> recent(int limit) {
        int size = Math.max(1, Math.min(limit, 100));
        try {
            return mapper.findRecent(size);
        } catch (Exception e) {
            log.debug("[告警] 读取告警记录失败: {}", e.getMessage());
            return List.of();
        }
    }
}
