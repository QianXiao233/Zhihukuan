package com.zhka.controller;

import com.zhka.service.AuthService;
import com.zhka.service.AuthService.AuthUser;
import com.zhka.service.CameraSourceService;
import com.zhka.util.Params;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 监控画面来源：{@code /api/manage/camera/**}。
 *
 * <p>查看对所有登录用户开放；新增 / 修改 / 删除由 {@code ManagementConfig}
 * 统一限制为管理员（Level ≥ 3）。
 */
@RestController
@RequestMapping("/api/manage/camera")
public class ManageCameraController extends AbstractManageController {

    private final CameraSourceService cameraSourceService;

    public ManageCameraController(AuthService authService, CameraSourceService cameraSourceService) {
        super(authService);
        this.cameraSourceService = cameraSourceService;
    }

    @GetMapping("/list")
    public Map<String, Object> list(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, cameraSourceService.findAll());
    }

    @PostMapping("/add")
    public Map<String, Object> add(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        String error = cameraSourceService.create(params);
        return error == null ? ok(user, "画面来源已新增") : fail(user, error);
    }

    @PostMapping("/update")
    public Map<String, Object> update(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        Integer sourceId = Params.integer(params, "source_id");
        if (sourceId == null) {
            return fail(user, "缺少 source_id");
        }
        String error = cameraSourceService.update(sourceId, params);
        return error == null ? ok(user, "画面来源已更新") : fail(user, error);
    }

    @PostMapping("/delete")
    public Map<String, Object> delete(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam("sourceId") Integer sourceId) {
        AuthUser user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return cameraSourceService.delete(sourceId) ? ok(user, "画面来源已删除") : fail(user, "画面来源不存在");
    }
}
