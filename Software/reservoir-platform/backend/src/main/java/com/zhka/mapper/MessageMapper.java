package com.zhka.mapper;

import com.zhka.entity.Message;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/** 平台消息通知持久化。 */
@Mapper
public interface MessageMapper {

    @Insert("INSERT INTO message(id, level, type, content, is_read, create_time) "
            + "VALUES(#{id}, #{level}, #{type}, #{content}, #{read}, #{createTime})")
    int insert(Message message);

    @Select("SELECT id, level, type, content, is_read AS `read`, create_time FROM message ORDER BY create_time DESC")
    List<Message> findAll();

    @Select("SELECT id, level, type, content, is_read AS `read`, create_time FROM message ORDER BY create_time DESC LIMIT 1")
    Message latest();

    @Select("SELECT COUNT(*) FROM message")
    int count();

    @Select("SELECT COUNT(*) FROM message WHERE is_read = 0")
    int countUnread();

    @Update("UPDATE message SET is_read = 1 WHERE id = #{id}")
    int markRead(String id);

    @Update("UPDATE message SET is_read = 1 WHERE is_read = 0")
    int markAllRead();

    @Delete("DELETE FROM message WHERE id = #{id}")
    int delete(String id);
}
