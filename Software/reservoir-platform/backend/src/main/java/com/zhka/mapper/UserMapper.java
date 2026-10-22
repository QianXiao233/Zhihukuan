package com.zhka.mapper;

import com.zhka.entity.User;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Options;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 平台用户表 {@code user} 的数据访问。 */
@Mapper
public interface UserMapper {

    /** 按用户名精确查询（{@code BINARY} 保证大小写敏感，与原实现一致） */
    @Select("SELECT * FROM user WHERE BINARY username = #{username}")
    User findByUsername(String username);

    @Select("SELECT * FROM user")
    List<User> findAll();

    @Select("SELECT * FROM user WHERE id = #{id}")
    User findById(Integer id);

    @Insert("INSERT INTO user(username, password, level, remark) VALUES(#{username}, #{password}, #{level}, #{remark})")
    @Options(useGeneratedKeys = true, keyProperty = "id")
    int insert(User user);

    @Update("UPDATE user SET username=#{username}, password=#{password}, level=#{level}, remark=#{remark} WHERE id=#{id}")
    int update(User user);

    @Delete("DELETE FROM user WHERE id = #{id}")
    int delete(Integer id);
}
