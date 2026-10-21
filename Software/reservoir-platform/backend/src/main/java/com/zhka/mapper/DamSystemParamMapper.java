package com.zhka.mapper;

import com.zhka.entity.DamSystemParam;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 系统参数表 {@code dam_system_param} 的数据访问。 */
@Mapper
public interface DamSystemParamMapper {

    @Select("SELECT * FROM dam_system_param ORDER BY param_id")
    List<DamSystemParam> findAll();

    @Select("SELECT * FROM dam_system_param WHERE param_id = #{paramId}")
    DamSystemParam findById(Integer paramId);

    @Insert("INSERT INTO dam_system_param(param_code, param_name, param_low_value, param_high_value, param_type, remark) "
            + "VALUES(#{paramCode}, #{paramName}, #{paramLowValue}, #{paramHighValue}, #{paramType}, #{remark})")
    @Options(useGeneratedKeys = true, keyProperty = "paramId")
    int insert(DamSystemParam param);

    @Update("UPDATE dam_system_param SET param_code=#{paramCode}, param_name=#{paramName}, "
            + "param_low_value=#{paramLowValue}, param_high_value=#{paramHighValue}, "
            + "param_type=#{paramType}, remark=#{remark} WHERE param_id=#{paramId}")
    int update(DamSystemParam param);

    @Delete("DELETE FROM dam_system_param WHERE param_id = #{paramId}")
    int delete(Integer paramId);
}
