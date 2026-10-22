package com.zhka.service;

import com.zhka.entity.Message;
import com.zhka.mapper.MessageMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 预警 / 通知消息用例，统一落到 MySQL，避免重启丢失。
 *
 * <p>通知内容是共享的（一条 {@code message}），每个用户的已读和弹窗确认
 * 存在 {@code message_recipient}，所以一个人点“我知道了”不会影响其他人。
 */
@Service
public class MessageService {

    private static final Logger log = LoggerFactory.getLogger(MessageService.class);
    private final MessageMapper messageMapper;

    public MessageService(MessageMapper messageMapper) {
        this.messageMapper = messageMapper;
    }

    /** 旧接口：只写 message，不指定接收人（外部采集端兼容用） */
    public Message add(Message message) {
        if (message.getCreateTime() == null) {
            message.setCreateTime(new java.sql.Timestamp(System.currentTimeMillis()));
        }
        messageMapper.insert(message);
        log.info("新增消息 id={}", message.getId());
        return message;
    }

    /**
     * 发布通知并给每位接收人建立状态行。
     *
     * @param recipients 接收人用户名（“全部”由调用方展开成当前所有用户）
     */
    @Transactional
    public Message publish(Message message, List<String> recipients) {
        if (message.getCreateTime() == null) {
            message.setCreateTime(new java.sql.Timestamp(System.currentTimeMillis()));
        }
        messageMapper.insert(message);
        for (String username : recipients) {
            messageMapper.insertRecipient(message.getId(), username);
        }
        log.info("发布通知 id={} 接收人={}", message.getId(), recipients.size());
        return message;
    }

    public List<Message> findForUser(String username) {
        return messageMapper.findByUser(username);
    }

    public int countUnreadForUser(String username) {
        return messageMapper.countUnreadForUser(username);
    }

    public void markReadForUser(String messageId, String username) {
        messageMapper.markReadForUser(messageId, username);
    }

    public void markAllReadForUser(String username) {
        messageMapper.markAllReadForUser(username);
    }

    public void deleteForUser(String messageId, String username) {
        messageMapper.deleteForUser(messageId, username);
    }

    /** 管理员撤回：内容与所有接收人的状态一起删除 */
    @Transactional
    public void recall(String messageId) {
        messageMapper.deleteRecipients(messageId);
        messageMapper.delete(messageId);
    }

    public List<Message> pendingPopups(String username) {
        return messageMapper.findPendingPopups(username);
    }

    public void markPopupDone(String messageId, String username) {
        messageMapper.markPopupDone(messageId, username);
    }

    // ─────────── 旧接口：外部采集端保留全局语义 ───────────

    public List<Message> findAll() {
        return messageMapper.findAll();
    }

    public void deleteById(String id) {
        messageMapper.delete(id);
    }

    public int count() {
        return messageMapper.count();
    }

    public Message latest() {
        return messageMapper.latest();
    }

    public int countUnread() {
        return messageMapper.countUnread();
    }

    public void markRead(String id) {
        messageMapper.markRead(id);
    }

    public void markAllRead() {
        messageMapper.markAllRead();
    }
}
