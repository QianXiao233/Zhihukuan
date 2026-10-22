package com.zhka.repository;

import com.zhka.entity.BusMessage;
import org.springframework.data.mongodb.repository.MongoRepository;

import java.util.Optional;

/** 中转消息仓储（简单查询）。 */
public interface BusMessageRepository extends MongoRepository<BusMessage, String> {

    Optional<BusMessage> findByMsgId(String msgId);

    long countByStatus(String status);
}
