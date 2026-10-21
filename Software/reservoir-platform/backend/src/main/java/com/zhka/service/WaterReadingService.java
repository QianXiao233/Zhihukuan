package com.zhka.service;

import com.zhka.common.BusinessException;
import com.zhka.config.PlatformProperties;
import com.zhka.dto.Thresholds;
import com.zhka.dto.WaterQuery;
import com.zhka.dto.WaterReadingView;
import com.zhka.entity.Metric;
import com.zhka.entity.WaterLog;
import com.zhka.entity.WaterReading;
import com.zhka.mapper.WaterLogMapper;
import com.zhka.repository.WaterReadingQueryRepository;
import com.zhka.repository.WaterReadingRepository;
import com.zhka.util.TimeParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.function.Supplier;

/**
 * 水情记录（MongoDB）的读写用例。
 *
 * <p>职责：
 * <ul>
 *   <li>采集落库（{@link #save}，失败只记日志，不影响 MQTT 采集）；</li>
 *   <li>筛选分页、聚合统计、趋势分桶；</li>
 *   <li>CSV 导出、按时间清理；</li>
 *   <li>把旧 MySQL 表 {@code water_log} 的历史数据迁移过来（幂等，可重复执行）。</li>
 * </ul>
 *
 * <p>MongoDB 不可用时，查询类接口统一抛 503 并给出可读提示，
 * 而不是让前端看到 500 的「服务暂时不可用」。
 */
@Service
public class WaterReadingService {

    private static final Logger log = LoggerFactory.getLogger(WaterReadingService.class);

    /** 导出上限，和旧接口保持一致 */
    public static final int EXPORT_LIMIT = 10_000;

    /** 趋势图最多返回的桶数，避免一个月的数据把页面撑爆 */
    private static final int MAX_BUCKETS = 720;

    /** 迁移时每批处理的旧数据条数 */
    private static final int MIGRATION_BATCH = 500;

    private final WaterReadingRepository repository;
    private final WaterReadingQueryRepository queryRepository;
    private final WaterLogMapper legacyMapper;
    private final ThresholdProvider thresholdProvider;
    private final PlatformProperties platform;

    public WaterReadingService(WaterReadingRepository repository,
                               WaterReadingQueryRepository queryRepository,
                               WaterLogMapper legacyMapper,
                               ThresholdProvider thresholdProvider,
                               PlatformProperties platform) {
        this.repository = repository;
        this.queryRepository = queryRepository;
        this.legacyMapper = legacyMapper;
        this.thresholdProvider = thresholdProvider;
        this.platform = platform;
    }

    // ─────────────────────────── 写入 ───────────────────────────

    /** 采集落库：补时间与来源，失败只记日志 */
    public void save(WaterReading reading) {
        if (reading == null) {
            return;
        }
        Instant now = Instant.now();
        if (reading.getTime() == null) {
            reading.setTime(now);
        }
        if (reading.getCreatedAt() == null) {
            reading.setCreatedAt(now);
        }
        if (reading.getSource() == null) {
            reading.setSource(WaterReading.SOURCE_MQTT);
        }
        try {
            queryRepository.ensureIndexes();
            repository.save(reading);
        } catch (Exception e) {
            log.warn("[水情] 写入 MongoDB 失败（MongoDB 可能未启动）: {}", message(e));
        }
    }

    // ─────────────────────────── 查询 ───────────────────────────

    /** 分页结果（record 序列化后就是 {rows,total,page,size}） */
    public record WaterPage(List<WaterReadingView> rows, long total, int page, int size) {
    }

    public WaterPage query(WaterQuery query) {
        return guarded("查询水情记录", () -> {
            Thresholds thresholds = thresholdProvider.current();
            long total = queryRepository.count(query, thresholds);
            if (total == 0) {
                return new WaterPage(List.of(), 0, query.getPage(), query.getSize());
            }
            List<WaterReading> readings = queryRepository.page(query, thresholds);
            List<WaterReadingView> rows = readings.stream()
                    .map(reading -> WaterReadingView.of(reading, thresholds))
                    .toList();
            return new WaterPage(rows, total, query.getPage(), query.getSize());
        });
    }

    /**
     * 聚合统计。
     *
     * @param granularity 趋势分桶粒度：{@code hour}（默认）/ {@code day}
     */
    public Map<String, Object> stats(WaterQuery query, String granularity) {
        return guarded("统计水情数据", () -> {
            Thresholds thresholds = thresholdProvider.current();
            Map<String, Object> aggregate = queryRepository.metricAggregate(query, thresholds);
            long total = number(aggregate.get("count"));

            List<Map<String, Object>> metrics = new ArrayList<>();
            for (Metric metric : Metric.values()) {
                Thresholds.MetricThreshold threshold = thresholds.of(metric);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("code", metric.code());
                item.put("field", metric.field());
                item.put("name", threshold == null ? metric.label() : threshold.name());
                item.put("unit", metric.unit());
                item.put("digits", metric.digits());
                item.put("low", threshold == null ? null : threshold.low());
                item.put("high", threshold == null ? null : threshold.high());
                item.put("avg", decimal(aggregate.get("avg_" + metric.field())));
                item.put("min", decimal(aggregate.get("min_" + metric.field())));
                item.put("max", decimal(aggregate.get("max_" + metric.field())));
                item.put("abnormalCount", queryRepository.countAbnormal(query, thresholds, metric));
                metrics.add(item);
            }

            List<Map<String, Object>> gates = new ArrayList<>();
            for (int index = 0; index < 6; index++) {
                long open = queryRepository.countGateOpen(query, thresholds, index);
                Map<String, Object> item = new LinkedHashMap<>();
                item.put("index", index + 1);
                item.put("open", open);
                item.put("closed", Math.max(0, total - open));
                item.put("openRate", total == 0 ? 0d : (double) open / total);
                gates.add(item);
            }

            List<Map<String, Object>> buckets =
                    new ArrayList<>(queryRepository.buckets(query, thresholds, granularity,
                            platform.zone(), MAX_BUCKETS));
            java.util.Collections.reverse(buckets);

            Map<String, Object> result = new LinkedHashMap<>();
            result.put("count", total);
            result.put("abnormalCount", queryRepository.countAbnormal(query, thresholds, null));
            result.put("metrics", metrics);
            result.put("gates", gates);
            result.put("buckets", normalizeBuckets(buckets));
            result.put("granularity", "day".equalsIgnoreCase(granularity) ? "day" : "hour");
            result.put("thresholdsConfigured", thresholds.anyConfigured());
            return result;
        });
    }

    /** 最近若干条（实时监测页的历史曲线用） */
    public List<WaterReadingView> recent(int limit) {
        return guarded("读取最近水情记录", () -> {
            WaterQuery query = new WaterQuery();
            query.withPage(1, Math.max(1, Math.min(limit, WaterQuery.MAX_PAGE_SIZE)));
            Thresholds thresholds = thresholdProvider.current();
            return queryRepository.page(query, thresholds).stream()
                    .map(reading -> WaterReadingView.of(reading, thresholds))
                    .toList();
        });
    }

    /** 最新一条原始文档，MongoDB 不可用时返回 null（监控状态展示用，不抛异常） */
    public WaterReading latestOrNull() {
        try {
            return queryRepository.latest();
        } catch (Exception e) {
            return null;
        }
    }

    // ─────────────────────────── 导出 / 清理 ───────────────────────────

    public String exportCsv(WaterQuery query) {
        return guarded("导出水情记录", () -> {
            Thresholds thresholds = thresholdProvider.current();
            long total = queryRepository.count(query, thresholds);
            if (total > EXPORT_LIMIT) {
                throw new BusinessException("导出最多 " + EXPORT_LIMIT + " 条，请缩小筛选范围", HttpStatus.BAD_REQUEST);
            }
            List<WaterReading> readings = queryRepository.page(query.forExport(EXPORT_LIMIT), thresholds);
            StringBuilder csv = new StringBuilder(
                    "\uFEFF时间,水位(m),液温(℃),pH,ORP(mV),闸门1,闸门2,闸门3,闸门4,闸门5,闸门6,状态,数据来源\n");
            for (WaterReading reading : readings) {
                WaterReadingView view = WaterReadingView.of(reading, thresholds);
                csv.append(TimeParser.format(reading.getTime(), platform.zone())).append(',')
                        .append(decimalText(reading.getLevel())).append(',')
                        .append(decimalText(reading.getTemperature())).append(',')
                        .append(decimalText(reading.getPh())).append(',')
                        .append(decimalText(reading.getOrp())).append(',');
                for (int index = 0; index < 6; index++) {
                    Integer state = gateOf(reading, index);
                    csv.append(state != null && state == 1 ? "开" : "关").append(',');
                }
                csv.append(view.isAbnormal() ? "超限(" + view.abnormalText() + ")" : "正常").append(',')
                        .append(WaterReading.SOURCE_MIGRATION.equals(reading.getSource()) ? "MySQL迁移" : "MQTT实时")
                        .append('\n');
            }
            return csv.toString();
        });
    }

    public long deleteBefore(Instant before) {
        return guarded("清理历史数据", () -> queryRepository.deleteBefore(before));
    }

    // ─────────────────────────── 迁移 / 状态 ───────────────────────────

    /**
     * 把旧 MySQL 表 {@code water_log} 的历史数据搬到 MongoDB。
     *
     * <p>按主键升序分批读取；每批先查 MongoDB 里已存在的 {@code legacyId}，只插入缺的。
     * 因此可以反复执行、中途失败后重跑，不会产生重复记录。
     */
    public Map<String, Object> migrateFromMySql() {
        return guarded("迁移历史水情数据", () -> {
            long started = System.currentTimeMillis();
            long lastId = 0L;
            int read = 0;
            int inserted = 0;
            int skipped = 0;
            Set<Long> seen = new HashSet<>();
            while (true) {
                List<WaterLog> batch = legacyMapper.scanAfterId(lastId, MIGRATION_BATCH);
                if (batch == null || batch.isEmpty()) {
                    break;
                }
                read += batch.size();
                lastId = batch.get(batch.size() - 1).getId();

                List<Long> ids = new ArrayList<>();
                for (WaterLog row : batch) {
                    if (row.getId() != null) {
                        ids.add(row.getId());
                    }
                }
                Set<Long> existing = new HashSet<>(queryRepository.existingLegacyIds(ids));
                List<WaterReading> documents = new ArrayList<>();
                for (WaterLog row : batch) {
                    if (row.getId() == null || existing.contains(row.getId()) || !seen.add(row.getId())) {
                        skipped++;
                        continue;
                    }
                    documents.add(toDocument(row));
                }
                if (!documents.isEmpty()) {
                    inserted += queryRepository.insertAll(documents);
                }
                if (batch.size() < MIGRATION_BATCH) {
                    break;
                }
            }
            Map<String, Object> result = new LinkedHashMap<>();
            result.put("read", read);
            result.put("inserted", inserted);
            result.put("skipped", skipped);
            result.put("elapsedMs", System.currentTimeMillis() - started);
            result.put("collection", WaterReading.COLLECTION);
            log.info("[水情] MySQL→MongoDB 迁移完成：读取 {} 条，写入 {} 条，跳过 {} 条", read, inserted, skipped);
            return result;
        });
    }

    /** 存储状态：前端用来提示「数据在哪、连没连上」 */
    public Map<String, Object> storageInfo() {
        Map<String, Object> info = new LinkedHashMap<>();
        info.put("engine", "MongoDB");
        info.put("collection", WaterReading.COLLECTION);
        boolean reachable = queryRepository.reachable();
        info.put("reachable", reachable);
        if (reachable) {
            try {
                info.put("documents", queryRepository.countAll());
                WaterReading latest = queryRepository.latest();
                info.put("latestTime", latest == null ? null : latest.getTime());
            } catch (Exception e) {
                info.put("documents", null);
                info.put("latestTime", null);
            }
        } else {
            info.put("documents", null);
            info.put("latestTime", null);
            info.put("message", "MongoDB 未连接，请检查 MONGO_URI 或服务是否启动");
        }
        try {
            info.put("legacyMysqlCount", legacyMapper.countAll());
        } catch (Exception e) {
            info.put("legacyMysqlCount", null);
        }
        return info;
    }

    // ─────────────────────────── 内部工具 ───────────────────────────

    private WaterReading toDocument(WaterLog legacy) {
        WaterReading reading = new WaterReading();
        reading.setTime(legacy.getTime() == null ? Instant.now() : legacy.getTime().toInstant());
        reading.setLevel((double) legacy.getLevel());
        reading.setTemperature((double) legacy.getTemperature());
        reading.setPh((double) legacy.getPh());
        reading.setOrp((double) legacy.getOrp());
        reading.setRelay1(legacy.getRelay1());
        reading.setRelay2(legacy.getRelay2());
        reading.setRelay3(legacy.getRelay3());
        reading.setRelay4(legacy.getRelay4());
        reading.setRelay5(legacy.getRelay5());
        reading.setRelay6(legacy.getRelay6());
        reading.setSource(WaterReading.SOURCE_MIGRATION);
        reading.setLegacyId(legacy.getId());
        reading.setCreatedAt(Instant.now());
        return reading;
    }

    /** 把聚合结果里的时区分桶键转成前端可直接用的结构 */
    private List<Map<String, Object>> normalizeBuckets(List<Map<String, Object>> raw) {
        List<Map<String, Object>> normalized = new ArrayList<>();
        for (Map<?, ?> bucket : raw) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("label", bucket.get("_id"));
            item.put("count", number(bucket.get("count")));
            item.put("avgLevel", decimal(bucket.get("avg_level")));
            item.put("minLevel", decimal(bucket.get("min_level")));
            item.put("maxLevel", decimal(bucket.get("max_level")));
            item.put("avgTemperature", decimal(bucket.get("avg_temperature")));
            normalized.add(item);
        }
        return normalized;
    }

    private static Integer gateOf(WaterReading reading, int index) {
        return switch (index) {
            case 0 -> reading.getRelay1();
            case 1 -> reading.getRelay2();
            case 2 -> reading.getRelay3();
            case 3 -> reading.getRelay4();
            case 4 -> reading.getRelay5();
            case 5 -> reading.getRelay6();
            default -> null;
        };
    }

    private static long number(Object value) {
        return value instanceof Number number ? number.longValue() : 0L;
    }

    private static Double decimal(Object value) {
        if (value instanceof Number number) {
            double result = number.doubleValue();
            return Double.isFinite(result) ? result : null;
        }
        return null;
    }

    private static String decimalText(Double value) {
        return value == null ? "" : String.valueOf(Math.round(value * 100d) / 100d);
    }

    private static String message(Throwable error) {
        Throwable current = error;
        while (current.getCause() != null && current.getCause() != current) {
            current = current.getCause();
        }
        return current.getMessage() == null ? current.getClass().getSimpleName() : current.getMessage();
    }

    /** 把 MongoDB 驱动异常统一转成 503 + 可读提示（驱动细节只进日志，不回给页面） */
    private static <T> T guarded(String action, Supplier<T> supplier) {
        try {
            return supplier.get();
        } catch (BusinessException e) {
            throw e;
        } catch (Exception e) {
            log.warn("[水情] {}失败: {}", action, message(e));
            throw new BusinessException("MongoDB 不可用，" + action + "失败，请检查 MONGO_URI 或数据库服务是否启动",
                    HttpStatus.SERVICE_UNAVAILABLE);
        }
    }
}
