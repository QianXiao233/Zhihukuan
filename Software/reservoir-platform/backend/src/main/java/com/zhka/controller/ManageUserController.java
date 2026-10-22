package com.zhka.controller;

import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.UserService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 用户管理：{@code /api/manage/user/**}。 */
@RestController
@RequestMapping("/api/manage/user")
public class ManageUserController extends AbstractManageController {

    private final UserService userService;

    public ManageUserController(AuthService authService, UserService userService) {
        super(authService);
        this.userService = userService;
    }

    @GetMapping("/list")
    public Map<String, Object> list(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        if (user.level() == null || (user.level() != 0 && user.level() < 3)) {
            return fail(user, "仅系统管理员可管理账号");
        }
        return okWithData(user, userService.findAll());
    }

    @PostMapping("/add")
    public Map<String, Object> add(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("username") String username,
            @RequestParam("password") String password,
            @RequestParam("level") Integer level,
            @RequestParam(value = "remark", required = false, defaultValue = "") String remark) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        if (user.level() == null || (user.level() != 0 && user.level() < 3)) {
            return fail(user, "仅系统管理员可管理账号");
        }
        if (username.isBlank() || password.length() < 6 || level < 1 || level > 3) return fail(user, "请输入账号、至少六位的密码和有效权限等级");
        if (remark.length() > 500) return fail(user, "备注最多 500 个字符");
        if (!userService.create(username, password, level, remark)) {
            return fail(user, "用户名已存在");
        }
        return ok(user, "新增成功");
    }

    @PostMapping("/update")
    public Map<String, Object> update(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("id") Integer id,
            @RequestParam("username") String username,
            @RequestParam(value = "password", defaultValue = "") String password,
            @RequestParam("level") Integer level,
            @RequestParam(value = "remark", required = false, defaultValue = "") String remark) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        if (user.level() == null || (user.level() != 0 && user.level() < 3)) {
            return fail(user, "仅系统管理员可管理账号");
        }
        var target = userService.findById(id);
        if (target == null) return fail(user, "用户不存在");
        if (user.username().equals(target.getUsername()) && (!username.equals(user.username()) || !level.equals(user.level())))
            return fail(user, "不能修改当前账号的用户名或权限，请使用另一管理员账号操作");
        if (username.isBlank() || level < 0 || level > 3 || (!password.isBlank() && password.length() < 6))
            return fail(user, "账号、密码或权限等级不符合要求");
        if (remark.length() > 500) return fail(user, "备注最多 500 个字符");
        if (!userService.update(id, username, password, level, remark)) {
            return fail(user, "用户不存在或用户名已被使用");
        }
        return ok(user, "更新成功");
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("id") Integer id) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        if (user.level() == null || (user.level() != 0 && user.level() < 3)) {
            return fail(user, "仅系统管理员可管理账号");
        }
        if (userService.findById(id) != null && user.username().equals(userService.findById(id).getUsername())) {
            return fail(user, "不能删除当前登录账号");
        }
        userService.delete(id);
        return ok(user, "删除成功");
    }

    @PostMapping("/password")
    public Map<String, Object> changePassword(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("oldPassword") String oldPassword,
            @RequestParam("newPassword") String newPassword) {
        AuthUser user = currentUser(authorization);
        if (user == null) return tokenInvalid();
        String error = userService.changePassword(user.username(), oldPassword, newPassword);
        return error == null ? ok(user, "密码已修改，请重新登录") : fail(user, error);
    }
}
