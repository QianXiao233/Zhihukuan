package com.zhka.controller;

import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.DamSystemParamService;
import com.zhka.service.ThresholdProvider;
import com.zhka.util.Params;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 系统参数管理：{@code /api/manage/param/**}。 */
@RestController
@RequestMapping("/api/manage/param")
public class ManageParamController extends AbstractManageController {

    private final DamSystemParamService damSystemParamService;
    private final ThresholdProvider thresholdProvider;

    public ManageParamController(AuthService authService, DamSystemParamService damSystemParamService,
                                 ThresholdProvider thresholdProvider) {
        super(authService);
        this.damSystemParamService = damSystemParamService;
        this.thresholdProvider = thresholdProvider;
    }

    @GetMapping("/list")
    public Map<String, Object> list(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, damSystemParamService.findAll());
    }

    @PostMapping("/add")
    public Map<String, Object> add(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        damSystemParamService.create(params);
        thresholdProvider.invalidate();
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
        Integer paramId = Params.integer(params, "param_id");
        if (paramId == null) {
            return fail(user, "缺少 param_id");
        }
        if (!damSystemParamService.update(paramId, params)) {
            return fail(user, "参数不存在");
        }
        thresholdProvider.invalidate();
        return ok(user, "更新成功");
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("paramId") Integer paramId) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        damSystemParamService.delete(paramId);
        thresholdProvider.invalidate();
        return ok(user, "删除成功");
    }
}
