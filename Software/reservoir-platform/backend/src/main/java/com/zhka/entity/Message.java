package com.zhka.entity;

import java.sql.Timestamp;
import java.util.UUID;

/**
 * 预警 / 通知消息。消息由采集服务或 Python 侧推送，并持久化到 message 表。
 */
public class Message {

    private String id;
    private int level;
    private String type;
    private String content;
    private boolean read;
    private Timestamp createTime;

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

    public boolean isRead() { return read; }

    public void setRead(boolean read) { this.read = read; }

    public Timestamp getCreateTime() { return createTime; }

    public void setCreateTime(Timestamp createTime) { this.createTime = createTime; }
}
