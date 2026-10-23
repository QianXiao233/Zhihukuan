package com.zhka.mapper;

import com.zhka.entity.CameraSource;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 监控画面来源表 {@code camera_source} 的数据访问。 */
@Mapper
public interface CameraSourceMapper {

    @Select("SELECT * FROM camera_source ORDER BY sort_order, source_id")
    List<CameraSource> findAll();

    @Select("SELECT * FROM camera_source WHERE source_id = #{sourceId}")
    CameraSource findById(Integer sourceId);

    @Insert("INSERT INTO camera_source(source_name, location, protocol, source_url, play_url, gateway_url, "
            + "stream_key, enabled, sort_order, twin_label, remark) "
            + "VALUES(#{sourceName}, #{location}, #{protocol}, #{sourceUrl}, #{playUrl}, #{gatewayUrl}, "
            + "#{streamKey}, #{enabled}, #{sortOrder}, #{twinLabel}, #{remark})")
    @Options(useGeneratedKeys = true, keyProperty = "sourceId")
    int insert(CameraSource source);

    @Update("UPDATE camera_source SET source_name=#{sourceName}, location=#{location}, protocol=#{protocol}, "
            + "source_url=#{sourceUrl}, play_url=#{playUrl}, gateway_url=#{gatewayUrl}, stream_key=#{streamKey}, "
            + "enabled=#{enabled}, sort_order=#{sortOrder}, twin_label=#{twinLabel}, remark=#{remark} "
            + "WHERE source_id=#{sourceId}")
    int update(CameraSource source);

    /** 同一个数字孪生标签只保留一路画面：保存新绑定时清掉旧记录。 */
    @Update("UPDATE camera_source SET twin_label=NULL WHERE twin_label=#{twinLabel} AND source_id<>#{sourceId}")
    int clearTwinLabel(@Param("twinLabel") String twinLabel, @Param("sourceId") Integer sourceId);

    @Delete("DELETE FROM camera_source WHERE source_id = #{sourceId}")
    int delete(Integer sourceId);
}
