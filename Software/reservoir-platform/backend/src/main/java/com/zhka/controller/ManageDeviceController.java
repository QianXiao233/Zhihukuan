package com.zhka.controller;

import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.DamDeviceService;
import com.zhka.util.Params;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 设备台账管理：{@code /api/manage/device/**}。 */
@RestController
@RequestMapping("/api/manage/device")
public class ManageDeviceController extends AbstractManageController {

    private final DamDeviceService damDeviceService;

    public ManageDeviceController(AuthService authService, DamDeviceService damDeviceService) {
        super(authService);
        this.damDeviceService = damDeviceService;
    }

    @GetMapping("/list")
    public Map<String, Object> list(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, damDeviceService.findAll());
    }

    @PostMapping("/add")
    public Map<String, Object> add(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        if (Params.integer(params, "dam_id") == null) {
            return fail(user, "请选择所属水库");
        }
        damDeviceService.create(params);
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
        Integer deviceId = Params.integer(params, "device_id");
        if (deviceId == null) {
            return fail(user, "缺少 device_id");
        }
        if (!damDeviceService.update(deviceId, params)) {
            return fail(user, "设备不存在");
        }
        return ok(user, "更新成功");
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("deviceId") Integer deviceId) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        damDeviceService.delete(deviceId);
        return ok(user, "删除成功");
    }
}
