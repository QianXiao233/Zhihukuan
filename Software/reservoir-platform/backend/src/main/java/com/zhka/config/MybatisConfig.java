package com.zhka.config;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.context.annotation.Configuration;

/**
 * MyBatis 配置。
 *
 * <p>原扫描路径写的是 {@code cn.reservoir.platform.mapper}（历史包名），与本项目实际的
 * {@code com.zhka.mapper} 不一致——之前能跑只是因为 Mapper 接口都标了 {@code @Mapper}。
 * 这里修正为真实包路径，避免新增 Mapper 时出现难查的注入失败。
 */
@Configuration
@MapperScan("com.zhka.mapper")
public class MybatisConfig {
}
