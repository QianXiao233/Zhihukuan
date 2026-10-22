package com.zhka.controller;

import com.zhka.common.ApiResult;
import com.zhka.service.AuthService;
import com.zhka.service.BusClientService;
import com.zhka.service.BusService;
import com.zhka.util.Params;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 总线客户端管理（管理员）：{@code /api/manage/bus/**}。
 *
 * <p>创建时返回一次明文密钥，之后只能轮换，不再回显。
 */
@RestController
@RequestMapping("/api/manage/bus")
public class ManageBusController extends AbstractManageController {

    private final BusClientService clients;
    private final BusService bus;

    public ManageBusController(AuthService auth, BusClientService clients, BusService bus) {
        super(auth);
        this.clients = clients;
        this.bus = bus;
    }

    @GetMapping("/clients")
    public Map<String, Object> list(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, clients.list());
    }

    @PostMapping("/clients")
    public Map<String, Object> create(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        String clientId = Params.text(params, "client_id");
        if (clientId == null || clientId.isBlank()) {
            return fail(user, "缺少 client_id");
        }
        BusClientService.CreatedClient created = clients.create(clientId,
                Params.text(params, "client_name"),
                Params.text(params, "allow_publish"),
                Params.text(params, "allow_subscribe"));
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("client", created.client());
        data.put("secret", created.secret());
        return ApiResult.success("客户端已创建，密钥只显示这一次，请立即保存")
                .withUser(user.username(), user.level())
                .data(data)
                .toMap();
    }

    @PostMapping("/clients/enable")
    public Map<String, Object> enable(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        String clientId = Params.text(params, "client_id");
        if (clientId == null || clientId.isBlank()) {
            return fail(user, "缺少 client_id");
        }
        boolean enabled = !"false".equalsIgnoreCase(Params.text(params, "enabled"));
        if (!clients.setEnabled(clientId, enabled)) {
            return fail(user, "客户端不存在");
        }
        return ok(user, enabled ? "已启用" : "已停用");
    }

    @PostMapping("/clients/delete")
    public Map<String, Object> delete(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        String clientId = Params.text(params, "client_id");
        if (clientId == null || clientId.isBlank()) {
            return fail(user, "缺少 client_id");
        }
        if (!clients.delete(clientId)) {
            return fail(user, "客户端不存在");
        }
        return ok(user, "客户端已删除");
    }

    @PostMapping("/clients/rotate")
    public Map<String, Object> rotate(
            @RequestHeader(value = "Authorization", required = false) String authorization,
            @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        String clientId = Params.text(params, "client_id");
        if (clientId == null || clientId.isBlank()) {
            return fail(user, "缺少 client_id");
        }
        String secret = clients.rotate(clientId);
        return ApiResult.success("密钥已轮换，旧密钥立即失效")
                .withUser(user.username(), user.level())
                .data(Map.of("clientId", clientId, "secret", secret))
                .toMap();
    }

    @GetMapping("/status")
    public Map<String, Object> status(
            @RequestHeader(value = "Authorization", required = false) String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("counts", bus.counts());
        data.put("clients", clients.list());
        return okWithData(user, data);
    }
}
