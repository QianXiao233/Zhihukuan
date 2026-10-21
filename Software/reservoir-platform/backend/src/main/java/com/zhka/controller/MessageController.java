package com.zhka.controller;

import com.zhka.entity.Message;
import com.zhka.service.MessageService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.UUID;

/**
 * 预警 / 通知消息接口。
 *
 * <p>供 Python 侧推送消息：{@code /api/add_message}、{@code /api/delete_message}；
 * 前端轮询 {@code /api/get_message}、{@code /api/get_messagelist}、{@code /api/get_messagecount}，
 * 并通过已读接口维护通知状态。
 */
@RestController
@RequestMapping("/api")
public class MessageController {

    private final MessageService messageService;

    public MessageController(MessageService messageService) {
        this.messageService = messageService;
    }

    @PostMapping("/add_message")
    public Map<String, Object> addMessage(@RequestParam("level") int level,
                                          @RequestParam("type") String type,
                                          @RequestParam("content") String content) {
        Message message = messageService.add(new Message(UUID.randomUUID().toString(), level, type, content));
        return Map.of("messageid", message.getId());
    }

    @PostMapping("/delete_message")
    public Map<String, Object> deleteMessage(@RequestParam("id") String id) {
        messageService.deleteById(id);
        return Map.of("messageid", id);
    }

    @GetMapping("/get_messagelist")
    public Map<String, Object> getMessageList() {
        return Map.of("messagelist", messageService.findAll());
    }

    /** 最新一条消息；没有消息时返回空响应体（与原接口一致） */
    @GetMapping("/get_message")
    public Message getMessage() {
        return messageService.latest();
    }

    @GetMapping("/get_messagecount")
    public int getMessageCount() {
        return messageService.count();
    }

    @GetMapping("/get_unread_messagecount")
    public int getUnreadMessageCount() {
        return messageService.countUnread();
    }

    @PostMapping("/mark_message_read")
    public Map<String, Object> markMessageRead(@RequestParam("id") String id) {
        messageService.markRead(id);
        return Map.of("messageid", id);
    }

    @PostMapping("/mark_all_messages_read")
    public Map<String, Object> markAllMessagesRead() {
        messageService.markAllRead();
        return Map.of("success", true);
    }
}
