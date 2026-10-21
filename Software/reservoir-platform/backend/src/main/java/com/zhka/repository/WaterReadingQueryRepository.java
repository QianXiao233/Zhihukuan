package com.zhka.repository;

import com.zhka.dto.Thresholds;
import com.zhka.dto.WaterQuery;
import com.zhka.entity.Metric;
import com.zhka.entity.WaterReading;
import org.springframework.data.domain.Sort;
import org.springframework.data.mongodb.core.MongoTemplate;
import org.springframework.data.mongodb.core.aggregation.Aggregation;
import org.springframework.data.mongodb.core.aggregation.AggregationResults;
import org.springframework.data.mongodb.core.aggregation.DateOperators;
import org.springframework.data.mongodb.core.index.Index;
import org.springframework.data.mongodb.core.index.IndexOperations;
import org.springframework.data.mongodb.core.query.Criteria;
import org.springframework.data.mongodb.core.query.Query;
import org.springframework.stereotype.Repository;

import java.time.Instant;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;

/**
 * 水情记录的组合查询（动态筛选 + 聚合统计）。
 *
 * <p>{@link WaterReadingRepository} 只提供按 id 的 CRUD；这里用 {@link MongoTemplate}
 * 拼动态条件，避免为一个筛选页写出十几条注解 SQL 风格的固定查询。
 *
 * <p>设计约定：所有方法在「没有可匹配条件」时返回空结果，不抛异常；
 * MongoDB 不可用时的异常由上层 {@code WaterReadingService} 捕获并转成业务提示。
 */
@Repository
public class WaterReadingQueryRepository {

    private final MongoTemplate mongo;

    /** 索引只创建一次；volatile + 双重检查，避免并发写入时重复建索引 */
    private volatile boolean indexReady = false;

    public WaterReadingQueryRepository(MongoTemplate mongo) {
        this.mongo = mongo;
    }

    /**
     * 拼基础条件。
     *
     * @return {@code null} 表示「该组合不可能命中任何记录」（例如只看越界但一个阈值都没配）
     */
    private Criteria criteria(WaterQuery query, Thresholds thresholds) {
        List<Criteria> all = new ArrayList<>();
        if (query.getStart() != null) {
            all.add(Criteria.where("time").gte(query.getStart()));
        }
        if (query.getEnd() != null) {
            all.add(Criteria.where("time").lte(query.getEnd()));
        }

        range(all, "level", query.getMinLevel(), query.getMaxLevel());
        range(all, "temperature", query.getMinTemperature(), query.getMaxTemperature());
        range(all, "ph", query.getMinPh(), query.getMaxPh());
        range(all, "orp", query.getMinOrp(), query.getMaxOrp());

        for (int index = 0; index < 6; index++) {
            Integer gate = query.relay(index);
            if (gate != null) {
                all.add(Criteria.where("relay" + (index + 1)).is(gate));
            }
        }

        if (query.isAbnormalOnly()) {
            List<Criteria> abnormal = new ArrayList<>();
            for (Metric metric : Metric.values()) {
                Thresholds.MetricThreshold threshold = thresholds == null ? null : thresholds.of(metric);
                if (threshold == null || !threshold.configured()) {
                    continue;
                }
                if (threshold.low() != null) {
                    abnormal.add(Criteria.where(metric.field()).lt(threshold.low()));
                }
                if (threshold.high() != null) {
                    abnormal.add(Criteria.where(metric.field()).gt(threshold.high()));
                }
            }
            if (abnormal.isEmpty()) {
                // 只筛越界，但没有配置任何阈值：结果必然是空，不能退化成「全部」
                return null;
            }
            all.add(new Criteria().orOperator(abnormal.toArray(new Criteria[0])));
        }

        if (all.isEmpty()) {
            return new Criteria();
        }
        return new Criteria().andOperator(all.toArray(new Criteria[0]));
    }

    private static void range(List<Criteria> all, String field, Double min, Double max) {
        if (min != null) {
            all.add(Criteria.where(field).gte(min));
        }
        if (max != null) {
            all.add(Criteria.where(field).lte(max));
        }
    }

    /** 分页查询；条件不可能命中时返回空列表 */
    public List<WaterReading> page(WaterQuery query, Thresholds thresholds) {
        Criteria criteria = criteria(query, thresholds);
        if (criteria == null) {
            return List.of();
        }
        Query mongoQuery = new Query(criteria)
                .with(Sort.by(query.isDescending() ? Sort.Direction.DESC : Sort.Direction.ASC, "time")
                        .and(Sort.by(Sort.Direction.DESC, "_id")))
                .skip(query.offset())
                .limit(query.getSize());
        return mongo.find(mongoQuery, WaterReading.class);
    }

    public long count(WaterQuery query, Thresholds thresholds) {
        Criteria criteria = criteria(query, thresholds);
        if (criteria == null) {
            return 0;
        }
        return mongo.count(new Query(criteria), WaterReading.class);
    }

    /** 越界记录数（可指定单个指标；metric 为 null 表示任一指标越界） */
    public long countAbnormal(WaterQuery query, Thresholds thresholds, Metric metric) {
        Criteria base = criteria(query, thresholds);
        if (base == null) {
            return 0;
        }
        List<Criteria> abnormal = new ArrayList<>();
        for (Metric candidate : Metric.values()) {
            if (metric != null && candidate != metric) {
                continue;
            }
            Thresholds.MetricThreshold threshold = thresholds == null ? null : thresholds.of(candidate);
            if (threshold == null || !threshold.configured()) {
                continue;
            }
            if (threshold.low() != null) {
                abnormal.add(Criteria.where(candidate.field()).lt(threshold.low()));
            }
            if (threshold.high() != null) {
                abnormal.add(Criteria.where(candidate.field()).gt(threshold.high()));
            }
        }
        if (abnormal.isEmpty()) {
            return 0;
        }
        Query mongoQuery = new Query(new Criteria().andOperator(base,
                new Criteria().orOperator(abnormal.toArray(new Criteria[0]))));
        return mongo.count(mongoQuery, WaterReading.class);
    }

    /** 某个闸门处于开启状态的记录数 */
    public long countGateOpen(WaterQuery query, Thresholds thresholds, int gateIndex) {
        Criteria base = criteria(query, thresholds);
        if (base == null) {
            return 0;
        }
        Query mongoQuery = new Query(new Criteria().andOperator(base,
                Criteria.where("relay" + (gateIndex + 1)).is(1)));
        return mongo.count(mongoQuery, WaterReading.class);
    }

    /**
     * 指标聚合：总量与各指标的 avg / min / max。
     *
     * @return 形如 {@code {count, avg_level, min_level, ...}}；无数据时返回空 Map
     */
    public Map<String, Object> metricAggregate(WaterQuery query, Thresholds thresholds) {
        Criteria criteria = criteria(query, thresholds);
        if (criteria == null) {
            return Map.of();
        }
        Aggregation aggregation = Aggregation.newAggregation(
                Aggregation.match(criteria),
                Aggregation.group()
                        .count().as("count")
                        .avg("level").as("avg_level")
                        .min("level").as("min_level")
                        .max("level").as("max_level")
                        .avg("temperature").as("avg_temperature")
                        .min("temperature").as("min_temperature")
                        .max("temperature").as("max_temperature")
                        .avg("ph").as("avg_ph")
                        .min("ph").as("min_ph")
                        .max("ph").as("max_ph")
                        .avg("orp").as("avg_orp")
                        .min("orp").as("min_orp")
                        .max("orp").as("max_orp")
        );
        AggregationResults<Map> results =
                mongo.aggregate(aggregation, WaterReading.COLLECTION, Map.class);
        Map<?, ?> row = results.getUniqueMappedResult();
        @SuppressWarnings("unchecked")
        Map<String, Object> typed = row == null ? Map.of() : (Map<String, Object>) row;
        return typed;
    }

    /**
     * 按小时 / 天分桶的趋势数据（按时间倒序取最近 limit 个桶，调用方反转成时间正序）。
     */
    public List<Map<String, Object>> buckets(WaterQuery query, Thresholds thresholds, String granularity,
                                             ZoneId zone, int limit) {
        Criteria criteria = criteria(query, thresholds);
        if (criteria == null) {
            return List.of();
        }
        String pattern = "day".equalsIgnoreCase(granularity) ? "%Y-%m-%d" : "%Y-%m-%d %H:00";
        Aggregation aggregation = Aggregation.newAggregation(
                Aggregation.match(criteria),
                Aggregation.project()
                        .and(DateOperators.DateToString.dateOf("time")
                                .toString(pattern)
                                .withTimezone(DateOperators.Timezone.valueOf(zone.getId())))
                        .as("bucket")
                        .and("level").as("level")
                        .and("temperature").as("temperature"),
                Aggregation.group("bucket")
                        .count().as("count")
                        .avg("level").as("avg_level")
                        .min("level").as("min_level")
                        .max("level").as("max_level")
                        .avg("temperature").as("avg_temperature"),
                Aggregation.sort(Sort.Direction.DESC, "_id"),
                Aggregation.limit(limit)
        );
        AggregationResults<Map> results =
                mongo.aggregate(aggregation, WaterReading.COLLECTION, Map.class);
        List<Map<String, Object>> rows = new ArrayList<>();
        for (Map row : results.getMappedResults()) {
            @SuppressWarnings("unchecked")
            Map<String, Object> typed = (Map<String, Object>) row;
            rows.add(typed);
        }
        return rows;
    }

    /** 删除某时间点之前的记录，返回删除条数 */
    public long deleteBefore(Instant before) {
        Query query = new Query(Criteria.where("time").lt(before));
        return mongo.remove(query, WaterReading.class).getDeletedCount();
    }

    /** 最新一条记录 */
    public WaterReading latest() {
        Query query = new Query().with(Sort.by(Sort.Direction.DESC, "time")).limit(1);
        return mongo.findOne(query, WaterReading.class);
    }

    public long countAll() {
        return mongo.count(new Query(), WaterReading.class);
    }

    /** 已迁移过的旧 MySQL id，用于断点续迁与幂等 */
    public List<Long> existingLegacyIds(Collection<Long> candidates) {
        if (candidates == null || candidates.isEmpty()) {
            return List.of();
        }
        Query query = new Query(Criteria.where("legacyId").in(candidates));
        query.fields().include("legacyId");
        return mongo.find(query, WaterReading.class).stream()
                .map(WaterReading::getLegacyId)
                .filter(java.util.Objects::nonNull)
                .toList();
    }

    /** 批量写入 */
    public int insertAll(List<WaterReading> readings) {
        if (readings == null || readings.isEmpty()) {
            return 0;
        }
        return mongo.insert(readings, WaterReading.class).size();
    }

    /** 是否连得上 MongoDB（用于状态展示，不抛异常） */
    public boolean reachable() {
        try {
            mongo.getCollectionNames();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    /** 集合名，供诊断信息使用 */
    public String collection() {
        return WaterReading.COLLECTION;
    }

    /**
     * 懒创建索引：第一次写入前调用。
     *
     * <p>不放在启动阶段，是为了遵守「数据库没启动也不阻塞应用启动」的约定：
     * 索引创建放在首次真正写库时，MongoDB 不在时只会在写入路径上报错一次。
     */
    public void ensureIndexes() {
        if (indexReady) {
            return;
        }
        synchronized (this) {
            if (indexReady) {
                return;
            }
            IndexOperations operations = mongo.indexOps(WaterReading.class);
            operations.ensureIndex(new Index().on("time", Sort.Direction.DESC));
            // 迁移幂等：旧 MySQL 主键唯一；非迁移数据该字段缺失，用稀疏索引跳过
            operations.ensureIndex(new Index().on("legacyId", Sort.Direction.ASC).unique().sparse());
            indexReady = true;
        }
    }
}
