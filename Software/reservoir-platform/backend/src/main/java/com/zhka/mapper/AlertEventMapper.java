package com.zhka.mapper;

import com.zhka.entity.AlertEvent;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 阈值告警记录表 {@code alert_event} 的数据访问。 */
@Mapper
public interface AlertEventMapper {

    @Insert("INSERT INTO alert_event(metric_code, metric_name, reading_value, low_threshold, high_threshold, "
            + "unit, direction, status, pushed, message, alert_time) "
            + "VALUES(#{metricCode}, #{metricName}, #{readingValue}, #{lowThreshold}, #{highThreshold}, "
            + "#{unit}, #{direction}, #{status}, #{pushed}, #{message}, #{time})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(AlertEvent event);

    // alert_time 在实体里叫 time，必须显式起别名，否则 map-underscore-to-camel-case
    // 会把它映射到并不存在的 alertTime 属性，读出来的时间是 null
    @Select("SELECT id, metric_code, metric_name, reading_value, low_threshold, high_threshold, "
            + "unit, direction, status, pushed, message, alert_time AS time "
            + "FROM alert_event ORDER BY alert_time DESC, id DESC LIMIT #{limit}")
    List<AlertEvent> findRecent(@Param("limit") int limit);
}
