package com.zhka.repository;

import com.zhka.entity.WaterReading;
import org.springframework.data.mongodb.repository.MongoRepository;

/**
 * 水情记录的简单仓储。
 *
 * <p>复杂筛选与聚合在 {@link WaterReadingQueryRepository} 里用 MongoTemplate 完成；
 * 这里只保留按主键读写，供落库与迁移使用。
 */
public interface WaterReadingRepository extends MongoRepository<WaterReading, String> {
}
