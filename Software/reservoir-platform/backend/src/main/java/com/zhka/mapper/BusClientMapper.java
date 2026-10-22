package com.zhka.mapper;

import com.zhka.entity.BusClient;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;
import org.apache.ibatis.annotations.Delete;

import java.util.List;

/** 总线客户端表 {@code bus_client} 的数据访问。 */
@Mapper
public interface BusClientMapper {

    @Select("SELECT * FROM bus_client ORDER BY created_at DESC")
    List<BusClient> findAll();

    @Select("SELECT * FROM bus_client WHERE client_id = #{clientId}")
    BusClient findById(@Param("clientId") String clientId);

    @Insert("INSERT INTO bus_client(client_id, client_name, secret_hash, allow_publish, allow_subscribe, enabled) "
            + "VALUES(#{clientId}, #{clientName}, #{secretHash}, #{allowPublish}, #{allowSubscribe}, #{enabled})")
    int insert(BusClient client);

    @Update("UPDATE bus_client SET enabled = #{enabled} WHERE client_id = #{clientId}")
    int updateEnabled(@Param("clientId") String clientId, @Param("enabled") boolean enabled);

    @Update("UPDATE bus_client SET secret_hash = #{secretHash} WHERE client_id = #{clientId}")
    int updateSecret(@Param("clientId") String clientId, @Param("secretHash") String secretHash);

    @Delete("DELETE FROM bus_client WHERE client_id = #{clientId}")
    int delete(@Param("clientId") String clientId);
}
