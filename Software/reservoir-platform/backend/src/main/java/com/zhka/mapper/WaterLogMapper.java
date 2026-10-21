package com.zhka.mapper;

import com.zhka.entity.WaterLog;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.sql.Timestamp;
import java.util.List;

/** 水情记录表 {@code water_log} 的数据访问。 */
@Mapper
public interface WaterLogMapper {

    /** 插入一条采集记录（MQTT 定时落库使用） */
    @Insert("INSERT INTO water_log(level, temperature, relay1, relay2, relay3, relay4, relay5, relay6, ph, orp, time) "
            + "VALUES(#{level}, #{temperature}, #{relay1}, #{relay2}, #{relay3}, #{relay4}, #{relay5}, #{relay6}, #{ph}, #{orp}, #{time})")
    int insert(WaterLog waterLog);

    @Select("SELECT * FROM water_log ORDER BY time DESC")
    List<WaterLog> findAll();

    @Select("SELECT * FROM water_log WHERE id = #{id}")
    WaterLog findById(Long id);

    /**
     * 按主键升序游标扫描，供「MySQL → MongoDB」迁移使用。
     *
     * <p>用 {@code id > afterId} 而不是 OFFSET：迁移中途失败可以直接从最后一条继续，
     * 也不会因为期间有插入而跳记录。
     */
    @Select("SELECT * FROM water_log WHERE id > #{afterId} ORDER BY id ASC LIMIT #{limit}")
    List<WaterLog> scanAfterId(@Param("afterId") long afterId, @Param("limit") int limit);

    @Select("SELECT * FROM water_log ORDER BY time DESC LIMIT #{limit}")
    List<WaterLog> findRecent(@Param("limit") int limit);

    @Select("SELECT * FROM water_log WHERE time >= #{startTime} ORDER BY time DESC")
    List<WaterLog> findByTimeAfter(@Param("startTime") Timestamp startTime);

    @Select("SELECT * FROM water_log WHERE time BETWEEN #{startTime} AND #{endTime} ORDER BY time ASC")
    List<WaterLog> findByTimeRange(@Param("startTime") Timestamp startTime,
                                   @Param("endTime") Timestamp endTime);

    @Delete("DELETE FROM water_log WHERE id = #{id}")
    int delete(Long id);

    /** 清理指定时间之前的旧数据（供后续定时清理任务使用） */
    @Delete("DELETE FROM water_log WHERE time < #{beforeTime}")
    int deleteBefore(@Param("beforeTime") Timestamp beforeTime);

    @Select("SELECT * FROM water_log WHERE time BETWEEN #{start} AND #{end} ORDER BY time DESC, id DESC LIMIT #{limit} OFFSET #{offset}")
    List<WaterLog> page(@Param("start") Timestamp start, @Param("end") Timestamp end,
                       @Param("limit") int limit, @Param("offset") int offset);

    @Select("SELECT COUNT(*) FROM water_log WHERE time BETWEEN #{start} AND #{end}")
    long countRange(@Param("start") Timestamp start, @Param("end") Timestamp end);

    @Select("SELECT COUNT(*) FROM water_log")
    long countAll();

    /**
     * 统计某时间点之后的聚合值。
     *
     * <p>注意：查询结果含 {@code count} 列，而 {@link WaterLog} 无对应属性，
     * MyBatis 会自动忽略；目前尚无调用方，后续若要使用建议改为独立的聚合 DTO。
     */
    @Select("SELECT AVG(level) as level, AVG(temperature) as temperature, "
            + "MAX(relay1) as relay1, MAX(relay2) as relay2, "
            + "MAX(relay3) as relay3, MAX(relay4) as relay4, "
            + "MAX(relay5) as relay5, MAX(relay6) as relay6, "
            + "AVG(ph) as ph, AVG(orp) as orp, "
            + "COUNT(*) as count "
            + "FROM water_log WHERE time >= #{startTime}")
    WaterLog statsSince(@Param("startTime") Timestamp startTime);
}
