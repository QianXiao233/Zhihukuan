package com.zhka.mapper;

import com.zhka.entity.PlatformSetting;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/** 平台键值配置表 {@code platform_setting} 的数据访问。 */
@Mapper
public interface PlatformSettingMapper {

    @Select("SELECT setting_key, setting_value FROM platform_setting")
    List<PlatformSetting> findAll();

    @Select("SELECT setting_value FROM platform_setting WHERE setting_key = #{key}")
    String findValue(@Param("key") String key);

    /** 存在则覆盖，不存在则插入（MySQL 的 upsert 写法） */
    @Insert("INSERT INTO platform_setting(setting_key, setting_value) VALUES(#{key}, #{value}) "
            + "ON DUPLICATE KEY UPDATE setting_value = VALUES(setting_value)")
    int upsert(@Param("key") String key, @Param("value") String value);
}
