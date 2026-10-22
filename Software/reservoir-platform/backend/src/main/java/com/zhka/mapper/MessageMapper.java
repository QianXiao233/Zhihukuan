package com.zhka.mapper;

import com.zhka.entity.Message;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Insert;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.annotations.Update;

import java.util.List;

/**
 * 平台消息通知持久化。
 *
 * <p>新接口都按 {@code message_recipient} 过滤到当前用户；
 * 末尾几个不带 username 的方法是给外部采集端（Python）保留的全局语义。
 */
@Mapper
public interface MessageMapper {

    @Insert("INSERT INTO message(id, level, type, content, is_read, create_time, popup, sound) "
            + "VALUES(#{id}, #{level}, #{type}, #{content}, #{read}, #{createTime}, #{popup}, #{sound})")
    int insert(Message message);

    /** 为一位接收人建立状态行；已读、弹窗确认都写在这行上 */
    @Insert("INSERT INTO message_recipient(message_id, username, is_read, popup_done) "
            + "VALUES(#{messageId}, #{username}, 0, 0)")
    int insertRecipient(@Param("messageId") String messageId, @Param("username") String username);

    @Select("SELECT m.id, m.level, m.type, m.content, m.create_time, m.popup, m.sound, "
            + "r.is_read AS `read`, r.popup_done AS popupDone "
            + "FROM message m JOIN message_recipient r ON r.message_id = m.id "
            + "WHERE r.username = #{username} ORDER BY m.create_time DESC, m.id DESC")
    List<Message> findByUser(@Param("username") String username);

    @Select("SELECT COUNT(*) FROM message m JOIN message_recipient r ON r.message_id = m.id "
            + "WHERE r.username = #{username} AND r.is_read = 0")
    int countUnreadForUser(@Param("username") String username);

    /** 登录补弹：当前用户还没确认过的弹窗通知 */
    @Select("SELECT m.id, m.level, m.type, m.content, m.create_time, m.popup, m.sound, "
            + "r.is_read AS `read`, r.popup_done AS popupDone "
            + "FROM message m JOIN message_recipient r ON r.message_id = m.id "
            + "WHERE r.username = #{username} AND r.popup_done = 0 AND r.is_read = 0 AND m.popup = 1 "
            + "ORDER BY m.create_time DESC, m.id DESC LIMIT 20")
    List<Message> findPendingPopups(@Param("username") String username);

    @Update("UPDATE message_recipient SET is_read = 1, popup_done = 1, read_time = NOW() "
            + "WHERE message_id = #{messageId} AND username = #{username}")
    int markReadForUser(@Param("messageId") String messageId, @Param("username") String username);

    @Update("UPDATE message_recipient SET is_read = 1, popup_done = 1, read_time = NOW() "
            + "WHERE username = #{username} AND is_read = 0")
    int markAllReadForUser(@Param("username") String username);

    @Update("UPDATE message_recipient SET popup_done = 1, is_read = 1, read_time = NOW() "
            + "WHERE message_id = #{messageId} AND username = #{username}")
    int markPopupDone(@Param("messageId") String messageId, @Param("username") String username);

    @Delete("DELETE FROM message_recipient WHERE message_id = #{messageId} AND username = #{username}")
    int deleteForUser(@Param("messageId") String messageId, @Param("username") String username);

    @Delete("DELETE FROM message_recipient WHERE message_id = #{messageId}")
    int deleteRecipients(@Param("messageId") String messageId);

    // ─────────── 旧接口：外部采集端使用的全局语义 ───────────

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
