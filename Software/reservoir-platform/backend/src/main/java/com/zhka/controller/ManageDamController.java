package com.zhka.controller;

import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.DamInfoService;
import com.zhka.util.Params;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 大坝基础信息管理：{@code /api/manage/dam/**}。 */
@RestController
@RequestMapping("/api/manage/dam")
public class ManageDamController extends AbstractManageController {

    private final DamInfoService damInfoService;

    public ManageDamController(AuthService authService, DamInfoService damInfoService) {
        super(authService);
        this.damInfoService = damInfoService;
    }

    @GetMapping("/list")
    public Map<String, Object> list(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, damInfoService.findAll());
    }

    @PostMapping("/add")
    public Map<String, Object> add(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        damInfoService.create(params);
        return ok(user, "新增成功");
    }

    @PostMapping("/update")
    public Map<String, Object> update(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        Integer damId = Params.integer(params, "dam_id");
        if (damId == null) {
            return fail(user, "缺少 dam_id");
        }
        if (!damInfoService.update(damId, params)) {
            return fail(user, "大坝不存在");
        }
        return ok(user, "更新成功");
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("damId") Integer damId) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        damInfoService.delete(damId);
        return ok(user, "删除成功");
    }
}
