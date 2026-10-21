package com.zhka.controller;

import com.zhka.entity.Message;
import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.MessageService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.UUID;

/** 经过平台身份校验的消息管理接口；旧式集成接口继续保留给外部采集端使用。 */
@RestController
@RequestMapping("/api/manage/messages")
public class ManageMessageController extends AbstractManageController {
    private final MessageService messages;

    public ManageMessageController(AuthService auth, MessageService messages) {
        super(auth);
        this.messages = messages;
    }

    @GetMapping("/list")
    public Map<String, Object> list(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        return user == null ? tokenInvalid() : okWithData(user, messages.findAll());
    }

    @GetMapping("/unread-count")
    public Map<String, Object> unreadCount(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        return user == null ? tokenInvalid() : okWithData(user, Map.of("count", messages.countUnread()));
    }

    @PostMapping("/read")
    public Map<String, Object> read(@RequestHeader(value = "Authorization", required = false) String authorization,
                                    @RequestParam("id") String id) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.markRead(id);
        return ok(user, "已标记为已读");
    }

    @PostMapping("/read-all")
    public Map<String, Object> readAll(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.markAllRead();
        return ok(user, "所有消息已标记为已读");
    }

    @PostMapping("/add")
    public Map<String, Object> add(@RequestHeader(value = "Authorization", required = false) String authorization,
                                   @RequestParam("level") int level,
                                   @RequestParam("type") String type,
                                   @RequestParam("content") String content) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        String cleanType = type == null ? "" : type.trim();
        String cleanContent = content == null ? "" : content.trim();
        if (level < 1 || level > 3 || cleanType.isBlank() || cleanContent.isBlank())
            return fail(user, "请填写通知类型、内容和有效级别");
        if (cleanType.length() > 50 || cleanContent.length() > 1000)
            return fail(user, "通知类型最多 50 个字符，内容最多 1000 个字符");
        messages.add(new Message(UUID.randomUUID().toString(), level, cleanType, cleanContent));
        return ok(user, "通知已发布");
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @RequestParam("id") String id) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.deleteById(id);
        return ok(user, "通知已删除");
    }
}
