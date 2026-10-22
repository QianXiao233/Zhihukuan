package com.zhka.service;

import com.zhka.config.PlatformProperties;
import com.zhka.dto.Thresholds;
import com.zhka.entity.DamSystemParam;
import com.zhka.entity.WaterReading;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.time.Instant;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.when;

/** AI 运行数据上下文：有数据时带读数，没数据时明确告知，不能编造。 */
@ExtendWith(MockitoExtension.class)
class PlatformRuntimeServiceTest {

    @Mock
    private WaterReadingService readings;
    @Mock
    private ThresholdProvider thresholds;
    @Mock
    private AlertService alerts;

    private PlatformRuntimeService service;

    @BeforeEach
    void setUp() {
        PlatformProperties platform = new PlatformProperties();
        platform.setStationName("门楼水库");
        platform.setZoneId("Asia/Shanghai");
        service = new PlatformRuntimeService(readings, thresholds, alerts, platform);
    }

    @Test
    void contextBlockContainsLiveReadingsAndThresholds() {
        when(readings.latestOrNull()).thenReturn(reading());
        when(thresholds.current()).thenReturn(thresholds());
        when(alerts.recent(3)).thenReturn(List.of());

        String block = service.contextBlock();
        assertTrue(block.contains("站点：门楼水库"));
        assertTrue(block.contains("水位：0.30 m"));
        assertTrue(block.contains("液温：26.1 ℃"));
        assertTrue(block.contains("pH：4.19"));
        assertTrue(block.contains("低于下限"));
        assertTrue(block.contains("闸门：1 关"));
        assertTrue(block.contains("最近告警：无"));
        assertTrue(block.contains("使用说明："));

        String augmented = service.augment("现在水位多少");
        assertTrue(augmented.startsWith("【平台实时数据】"));
        assertTrue(augmented.endsWith("用户问题：现在水位多少"));
    }

    @Test
    void missingDataIsExplicit() {
        when(readings.latestOrNull()).thenReturn(null);
        when(thresholds.current()).thenReturn(Thresholds.empty());

        String block = service.contextBlock();
        assertTrue(block.contains("当前没有收到 RTU 水情数据"));
        assertFalse(block.contains("水位："));
    }

    private static WaterReading reading() {
        WaterReading reading = new WaterReading();
        reading.setTime(Instant.now().minusSeconds(5));
        reading.setLevel(0.3);
        reading.setTemperature(26.1);
        reading.setPh(4.19);
        reading.setOrp(56.0);
        reading.setRelay1(0);
        reading.setRelay2(0);
        reading.setRelay3(0);
        reading.setRelay4(0);
        reading.setRelay5(0);
        reading.setRelay6(0);
        return reading;
    }

    private static Thresholds thresholds() {
        return Thresholds.from(List.of(
                param("water_level", "水位", "0.2", "1.2"),
                param("temperature", "液温", "5", "35"),
                param("ph", "pH", "6.5", "8.5"),
                param("orp", "ORP", "-100", "300")));
    }

    private static DamSystemParam param(String code, String name, String low, String high) {
        DamSystemParam param = new DamSystemParam();
        param.setParamCode(code);
        param.setParamName(name);
        param.setParamLowValue(low);
        param.setParamHighValue(high);
        return param;
    }
}
