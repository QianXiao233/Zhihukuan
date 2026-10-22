package com.zhka.entity;

import java.sql.Timestamp;
import java.util.UUID;

/**
 * 预警 / 通知消息。消息由采集服务或 Python 侧推送，并持久化到 message 表。
 *
 * <p>通知的接收人是多对多的：{@code message} 只存内容一次，
 * 每个用户的已读/弹窗确认状态在 {@code message_recipient} 里，
 * 所以一个用户确认不会影响其他用户。
 */
public class Message {

    private String id;
    private int level;
    private String type;
    private String content;
    private boolean read;
    private Timestamp createTime;
    /** 是否要求前端弹窗（需用户确认） */
    private boolean popup;
    /** 是否播放提示音 */
    private boolean sound;
    /** 当前登录用户是否已经确认过弹窗（来自 message_recipient） */
    private boolean popupDone;

    public Message() {
        this.id = UUID.randomUUID().toString();
        this.createTime = new Timestamp(System.currentTimeMillis());
    }

    public Message(String id, int level, String type, String content) {
        this.id = id;
        this.level = level;
        this.type = type;
        this.content = content;
        this.createTime = new Timestamp(System.currentTimeMillis());
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public int getLevel() {
        return level;
    }

    public void setLevel(int level) {
        this.level = level;
    }

    public String getType() {
        return type;
    }

    public void setType(String type) {
        this.type = type;
    }

    public String getContent() {
        return content;
    }

    public void setContent(String content) {
        this.content = content;
    }

    public boolean isRead() {
        return read;
    }

    public void setRead(boolean read) {
        this.read = read;
    }

    public Timestamp getCreateTime() {
        return createTime;
    }

    public void setCreateTime(Timestamp createTime) {
        this.createTime = createTime;
    }

    public boolean isPopup() {
        return popup;
    }

    public void setPopup(boolean popup) {
        this.popup = popup;
    }

    public boolean isSound() {
        return sound;
    }

    public void setSound(boolean sound) {
        this.sound = sound;
    }

    public boolean isPopupDone() {
        return popupDone;
    }

    public void setPopupDone(boolean popupDone) {
        this.popupDone = popupDone;
    }
}
