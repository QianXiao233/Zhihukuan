package com.zhka.controller;

import com.zhka.common.BusinessException;
import com.zhka.config.PlatformProperties;
import com.zhka.dto.WaterQuery;
import com.zhka.service.AuthService;
import com.zhka.service.WaterReadingService;
import com.zhka.util.TimeParser;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 水情数据（MongoDB）：筛选查询、聚合统计、导出、清理与历史迁移。
 *
 * <p>记录已经从 MySQL 的 {@code water_log} 搬到了 MongoDB 的 {@code water_readings}，
 * 这里的接口不再直接依赖 MyBatis；MySQL 只用于迁移旧数据。
 */
@RestController
@RequestMapping("/api/manage/data")
public class ManageDataController extends AbstractManageController {

    private final WaterReadingService waterService;
    private final PlatformProperties platform;

    public ManageDataController(AuthService auth, WaterReadingService waterService,
                                PlatformProperties platform) {
        super(auth);
        this.waterService = waterService;
        this.platform = platform;
    }

    /**
     * 兼容旧接口：实时监测页还在用它取「最近 N 条 + 总数」。
     *
     * <p>返回 {@code {count, recent}}；筛选参数与 {@link #query} 一致，可以只传时间范围。
     */
    @GetMapping("/summary")
    public Map<String, Object> summary(@RequestHeader("Authorization") String authorization,
                                       @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        WaterQuery query = WaterQuery.from(params, platform.zone());
        int limit = clampSize(params.get("limit"), query.getSize());
        int page = Math.max(1, intValue(params.get("page"), 1));
        WaterReadingService.WaterPage result = waterService.query(query.withPage(page, limit));
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("count", result.total());
        data.put("recent", result.rows());
        return okWithData(user, data);
    }

    /** 完整筛选条件的分页查询：{rows,total,page,size} */
    @GetMapping("/query")
    public Map<String, Object> query(@RequestHeader("Authorization") String authorization,
                                     @RequestParam Map<String, String> params) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        WaterQuery query = WaterQuery.from(params, platform.zone());
        return okWithData(user, waterService.query(query));
    }

    /** 聚合统计：总量、各指标 min/avg/max、越界数量、闸门开启率、趋势分桶 */
    @GetMapping("/stats")
    public Map<String, Object> stats(@RequestHeader("Authorization") String authorization,
                                     @RequestParam Map<String, String> params,
                                     @RequestParam(defaultValue = "hour") String granularity) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        WaterQuery query = WaterQuery.from(params, platform.zone());
        return okWithData(user, waterService.stats(query, granularity));
    }

    /** 按当前筛选条件导出 CSV（上限 10000 条） */
    @GetMapping(value = "/export", produces = "text/csv;charset=UTF-8")
    public ResponseEntity<String> export(@RequestParam Map<String, String> params) {
        WaterQuery query = WaterQuery.from(params, platform.zone());
        String csv = waterService.exportCsv(query);
        return ResponseEntity.ok()
                .header("Content-Disposition", "attachment; filename=water-log.csv")
                .body(csv);
    }

    /** 清理指定时间之前的数据（管理员） */
    @PostMapping("/clean-before")
    public Map<String, Object> cleanBefore(@RequestHeader("Authorization") String authorization,
                                           @RequestParam("beforeTime") String beforeTime) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        Instant before = TimeParser.parse(beforeTime, false, platform.zone());
        if (before == null) {
            return fail(user, "请选择要清理的时间点");
        }
        if (before.isAfter(Instant.now())) {
            return fail(user, "不能选择未来时间");
        }
        long deleted = waterService.deleteBefore(before);
        return ok(user, "已清理 " + deleted + " 条水情记录");
    }

    /** 把旧 MySQL 表 water_log 的历史数据迁移到 MongoDB（管理员，幂等） */
    @PostMapping("/migrate")
    public Map<String, Object> migrate(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, waterService.migrateFromMySql());
    }

    /** 存储状态：MySQL 旧表还剩多少条、MongoDB 是否连得上 */
    @GetMapping("/storage")
    public Map<String, Object> storage(@RequestHeader("Authorization") String authorization) {
        var user = currentUser(authorization);
        if (user == null) {
            return tokenInvalid();
        }
        return okWithData(user, waterService.storageInfo());
    }

    private static int clampSize(String text, int fallback) {
        int size = intValue(text, fallback);
        return Math.max(1, Math.min(size, WaterQuery.MAX_PAGE_SIZE));
    }

    private static int intValue(String text, int fallback) {
        if (text == null || text.isBlank()) {
            return fallback;
        }
        try {
            return Integer.parseInt(text.trim());
        } catch (NumberFormatException e) {
            throw new BusinessException("分页参数格式不正确", HttpStatus.BAD_REQUEST);
        }
    }
}
