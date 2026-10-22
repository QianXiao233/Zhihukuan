package com.zhka.controller;

import com.zhka.entity.Message;
import com.zhka.entity.User;
import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.BusService;
import com.zhka.service.MessageService;
import com.zhka.service.UserService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** 经过平台身份校验的消息管理接口；旧式集成接口继续保留给外部采集端使用。 */
@RestController
@RequestMapping("/api/manage/messages")
public class ManageMessageController extends AbstractManageController {

    private static final Logger log = LoggerFactory.getLogger(ManageMessageController.class);
    private static final int MAX_RECIPIENTS = 500;

    private final MessageService messages;
    private final BusService bus;
    private final UserService users;

    public ManageMessageController(AuthService auth, MessageService messages, BusService bus, UserService users) {
        super(auth);
        this.messages = messages;
        this.bus = bus;
        this.users = users;
    }

    @GetMapping("/list")
    public Map<String, Object> list(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        return user == null ? tokenInvalid() : okWithData(user, messages.findForUser(user.username()));
    }

    @GetMapping("/unread-count")
    public Map<String, Object> unreadCount(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        return user == null ? tokenInvalid()
                : okWithData(user, Map.of("count", messages.countUnreadForUser(user.username())));
    }

    /** 登录补弹：返回当前用户还没确认过的弹窗通知 */
    @GetMapping("/pending-popups")
    public Map<String, Object> pendingPopups(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        return user == null ? tokenInvalid() : okWithData(user, messages.pendingPopups(user.username()));
    }

    @PostMapping("/read")
    public Map<String, Object> read(@RequestHeader(value = "Authorization", required = false) String authorization,
                                    @RequestParam("id") String id) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.markReadForUser(id, user.username());
        return ok(user, "已标记为已读");
    }

    @PostMapping("/read-all")
    public Map<String, Object> readAll(@RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.markAllReadForUser(user.username());
        return ok(user, "所有消息已标记为已读");
    }

    /** 弹窗确认：只更新当前用户自己的状态 */
    @PostMapping("/popup-done")
    public Map<String, Object> popupDone(@RequestHeader(value = "Authorization", required = false) String authorization,
                                         @RequestParam("id") String id) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.markPopupDone(id, user.username());
        return ok(user, "已确认");
    }

    @PostMapping("/add")
    public Map<String, Object> add(@RequestHeader(value = "Authorization", required = false) String authorization,
                                   @RequestParam("level") int level,
                                   @RequestParam("type") String type,
                                   @RequestParam("content") String content,
                                   @RequestParam(value = "popup", defaultValue = "false") boolean popup,
                                   @RequestParam(value = "sound", defaultValue = "true") boolean sound,
                                   @RequestParam(value = "target_mode", defaultValue = "all") String targetMode,
                                   @RequestParam(value = "targets", required = false, defaultValue = "") String targets) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        String cleanType = type == null ? "" : type.trim();
        String cleanContent = content == null ? "" : content.trim();
        if (level < 1 || level > 3 || cleanType.isBlank() || cleanContent.isBlank())
            return fail(user, "请填写通知类型、内容和有效级别");
        if (cleanType.length() > 50 || cleanContent.length() > 1000)
            return fail(user, "通知类型最多 50 个字符，内容最多 1000 个字符");

        List<String> recipients = resolveRecipients(targetMode, targets);
        if (recipients == null) {
            return fail(user, "接收用户不存在：" + targets);
        }
        if (recipients.isEmpty()) {
            return fail(user, "没有可接收的用户");
        }
        if (recipients.size() > MAX_RECIPIENTS) {
            return fail(user, "单次最多发送给 " + MAX_RECIPIENTS + " 位用户");
        }

        Message message = new Message(UUID.randomUUID().toString(), level, cleanType, cleanContent);
        message.setPopup(popup);
        message.setSound(popup && sound);
        messages.publish(message, recipients);

        // 推送到前端默认订阅的 ui.# 频道；audience 限定只有这些用户会收到
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("title", cleanType);
            payload.put("content", cleanContent);
            payload.put("level", level);
            payload.put("popup", popup);
            payload.put("sound", popup && sound);
            payload.put("messageId", message.getId());
            payload.put("time", Instant.now().toString());
            bus.publishSystem(new BusService.PublishCommand("ui.notice", "notice", payload,
                    null, message.getId(), 3600L), recipients);
        } catch (Exception e) {
            log.warn("通知已保存，但推送到前端频道失败: {}", e.getMessage());
        }
        return ok(user, "通知已发布，已推送给 " + recipients.size() + " 位用户");
    }

    /**
     * 解析接收人。
     *
     * @return null 表示指定的用户名不存在；空列表表示没有接收人
     */
    private List<String> resolveRecipients(String targetMode, String targets) {
        if (!"users".equalsIgnoreCase(targetMode == null ? "" : targetMode.trim())) {
            return users.findAll().stream().map(User::getUsername).toList();
        }
        LinkedHashSet<String> selected = new LinkedHashSet<>();
        for (String raw : (targets == null ? "" : targets).split(",")) {
            String username = raw.trim();
            if (username.isEmpty()) continue;
            if (!users.exists(username)) return null;
            selected.add(username);
            if (selected.size() > MAX_RECIPIENTS) break;
        }
        return new ArrayList<>(selected);
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @RequestParam("id") String id) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        messages.deleteForUser(id, user.username());
        return ok(user, "通知已删除");
    }

    /** 管理员撤回：从所有用户的列表里移除这条通知 */
    @PostMapping("/recall")
    public Map<String, Object> recall(@RequestHeader(value = "Authorization", required = false) String authorization,
                                      @RequestParam("id") String id) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        if (user.level() == null || (user.level() != 0 && user.level() < 3)) {
            return fail(user, "仅管理员可撤回通知");
        }
        messages.recall(id);
        return ok(user, "通知已撤回");
    }
}
