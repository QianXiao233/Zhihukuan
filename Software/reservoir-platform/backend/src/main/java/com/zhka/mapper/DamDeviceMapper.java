package com.zhka.mapper;

import com.zhka.entity.DamDevice;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 设备台账表 {@code dam_device} 的数据访问。 */
@Mapper
public interface DamDeviceMapper {

    @Select("SELECT * FROM dam_device ORDER BY device_id")
    List<DamDevice> findAll();

    @Select("SELECT * FROM dam_device WHERE device_id = #{deviceId}")
    DamDevice findById(Integer deviceId);

    @Select("SELECT * FROM dam_device WHERE dam_id = #{damId}")
    List<DamDevice> findByDamId(Integer damId);

    @Insert("INSERT INTO dam_device(dam_id, device_name, device_code, device_type, manufacturer, model, "
            + "install_time, install_position, protocol, status, remark) "
            + "VALUES(#{damId}, #{deviceName}, #{deviceCode}, #{deviceType}, #{manufacturer}, #{model}, "
            + "#{installTime}, #{installPosition}, #{protocol}, #{status}, #{remark})")
    @Options(useGeneratedKeys = true, keyProperty = "deviceId")
    int insert(DamDevice device);

    @Update("UPDATE dam_device SET dam_id=#{damId}, device_name=#{deviceName}, device_code=#{deviceCode}, "
            + "device_type=#{deviceType}, manufacturer=#{manufacturer}, model=#{model}, "
            + "install_time=#{installTime}, install_position=#{installPosition}, protocol=#{protocol}, "
            + "status=#{status}, remark=#{remark} WHERE device_id=#{deviceId}")
    int update(DamDevice device);

    @Delete("DELETE FROM dam_device WHERE device_id = #{deviceId}")
    int delete(Integer deviceId);
}
