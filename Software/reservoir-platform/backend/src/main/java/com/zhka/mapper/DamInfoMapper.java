package com.zhka.mapper;

import com.zhka.entity.DamInfo;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 大坝基础信息表 {@code dam_info} 的数据访问。 */
@Mapper
public interface DamInfoMapper {

    @Select("SELECT * FROM dam_info ORDER BY dam_id")
    List<DamInfo> findAll();

    @Select("SELECT * FROM dam_info WHERE dam_id = #{damId}")
    DamInfo findById(Integer damId);

    @Insert("INSERT INTO dam_info(dam_name, dam_type, river_name, location, design_water_level, die_water_level, "
            + "flood_water_level, dam_height, dam_storage, control_area, build_year, status, remark) "
            + "VALUES(#{damName}, #{damType}, #{riverName}, #{location}, #{designWaterLevel}, #{dieWaterLevel}, "
            + "#{floodWaterLevel}, #{damHeight}, #{damStorage}, #{controlArea}, #{buildYear}, #{status}, #{remark})")
    @Options(useGeneratedKeys = true, keyProperty = "damId")
    int insert(DamInfo dam);

    @Update("UPDATE dam_info SET dam_name=#{damName}, dam_type=#{damType}, river_name=#{riverName}, "
            + "location=#{location}, design_water_level=#{designWaterLevel}, die_water_level=#{dieWaterLevel}, "
            + "flood_water_level=#{floodWaterLevel}, dam_height=#{damHeight}, dam_storage=#{damStorage}, "
            + "control_area=#{controlArea}, build_year=#{buildYear}, status=#{status}, remark=#{remark} "
            + "WHERE dam_id=#{damId}")
    int update(DamInfo dam);

    @Delete("DELETE FROM dam_info WHERE dam_id = #{damId}")
    int delete(Integer damId);
}
