package com.zhka.entity;

import com.fasterxml.jackson.annotation.JsonProperty;

/**
 * 平台登录用户。
 *
 * <p>对应表 {@code user}（列名 ID / UserName / PassWord / Level）。
 * 原类名 {@code UserService} 与 Service 层混淆，已更名。
 */
public class User {

    private Integer id;
    private String username;
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private String password;
    /** 权限等级，越大权限越高（沿用原平台约定） */
    private Integer level;
    /** 备注：岗位、所属单位等，便于通知按人发送时辨认 */
    private String remark;

    public Integer getId() {
        return id;
    }

    public void setId(Integer id) {
        this.id = id;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getPassword() {
        return password;
    }

    public void setPassword(String password) {
        this.password = password;
    }

    public Integer getLevel() {
        return level;
    }

    public void setLevel(Integer level) {
        this.level = level;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }
}
