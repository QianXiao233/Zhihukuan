package com.zhka.service;

import com.zhka.entity.Message;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.List;
import com.zhka.mapper.MessageMapper;

/**
 * 预警 / 通知消息用例，统一落到 MySQL，避免重启丢失。
 *
 * <p>原类名 {@code MessagelistService} 拼写不规范，已更名；
 * 消息条数改为直接取列表大小，避免计数器与列表不同步。
 */
@Service
public class MessageService {

    private static final Logger log = LoggerFactory.getLogger(MessageService.class);
    private final MessageMapper messageMapper;

    public MessageService(MessageMapper messageMapper) {
        this.messageMapper = messageMapper;
    }

    public Message add(Message message) {
        if (message.getCreateTime() == null) {
            message.setCreateTime(new java.sql.Timestamp(System.currentTimeMillis()));
        }
        messageMapper.insert(message);
        log.info("新增消息 id={}", message.getId());
        return message;
    }

    /** 删除指定 id；不存在时只记录日志，不报错 */
    public void deleteById(String id) {
        messageMapper.delete(id);
    }

    public List<Message> findAll() {
        return messageMapper.findAll();
    }

    public int count() {
        return messageMapper.count();
    }

    /** 最新一条消息；列表为空时返回 null */
    public Message latest() {
        return messageMapper.latest();
    }

    public int countUnread() { return messageMapper.countUnread(); }

    public void markRead(String id) { messageMapper.markRead(id); }

    public void markAllRead() { messageMapper.markAllRead(); }
}
