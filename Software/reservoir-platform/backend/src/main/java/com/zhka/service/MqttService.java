package com.zhka.service;

import com.alibaba.fastjson.JSON;
import com.alibaba.fastjson.JSONArray;
import com.alibaba.fastjson.JSONObject;
import com.zhka.config.PlatformProperties;
import com.zhka.entity.WaterReading;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import org.eclipse.paho.client.mqttv3.IMqttDeliveryToken;
import org.eclipse.paho.client.mqttv3.MqttCallback;
import org.eclipse.paho.client.mqttv3.MqttClient;
import org.eclipse.paho.client.mqttv3.MqttConnectOptions;
import org.eclipse.paho.client.mqttv3.MqttException;
import org.eclipse.paho.client.mqttv3.MqttMessage;
import org.eclipse.paho.client.mqttv3.persist.MemoryPersistence;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.Instant;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * 订阅 RTU 上报的水情数据：实时比对阈值，并按固定间隔把最新一条写入 MongoDB。
 *
 * <p>隔离要求：MQTT 未启动、MongoDB 未启动都不得影响应用启动与问答功能。
 * 因此连接失败只记日志、定时落库失败只丢弃当批数据，均不向上抛异常。
 */
@Service
public class MqttService {

    private static final Logger log = LoggerFactory.getLogger(MqttService.class);

    private static final int CONNECTION_TIMEOUT_SECONDS = 10;
    private static final int KEEP_ALIVE_SECONDS = 60;
    /** 首次连接失败后的重试间隔 */
    private static final int RECONNECT_INTERVAL_SECONDS = 30;

    private final WaterReadingService waterReadingService;
    private final ThresholdMonitorService monitor;
    private final PlatformProperties properties;

    private MqttClient mqttClient;
    private ScheduledExecutorService scheduler;

    /** 只保留最新一条数据 */
    private final Object lock = new Object();
    private WaterReading latestReading;
    private boolean hasNewData;

    public MqttService(WaterReadingService waterReadingService, ThresholdMonitorService monitor,
                       PlatformProperties properties) {
        this.waterReadingService = waterReadingService;
        this.monitor = monitor;
        this.properties = properties;
    }

    @PostConstruct
    public void init() {
        if (!properties.isEnabled()) {
            log.info("[平台] 已整体禁用（reservoir.platform.enabled=false），跳过 MQTT 采集");
            return;
        }
        if (!properties.getMqtt().isEnabled()) {
            log.info("[MQTT] 已禁用（reservoir.platform.mqtt.enabled=false）");
            return;
        }
        startScheduledSave();
        // 立刻尝试连接；失败后由同一个调度器每 30 秒重试一次。
        scheduler.scheduleWithFixedDelay(() -> {
            if (!isConnected()) {
                connectOnce();
            }
        }, 0, RECONNECT_INTERVAL_SECONDS, TimeUnit.SECONDS);
    }

    @PreDestroy
    public void destroy() {
        closeQuietly(mqttClient);
        mqttClient = null;
        if (scheduler != null) {
            scheduler.shutdown();
            saveLatest();
        }
    }

    /** 连接一次；失败只记日志，等下一轮重试，绝不向上抛异常影响启动 */
    private synchronized void connectOnce() {
        if (isConnected()) {
            return;
        }
        // 上一条连接断开后，Paho 的 automaticReconnect 可能还在后台重连；
        // 不先关掉它，新连接会顶着同一个 clientId 和它互相踢，表现为反复"连上又断"。
        if (mqttClient != null) {
            closeQuietly(mqttClient);
            mqttClient = null;
        }
        PlatformProperties.Mqtt mqtt = properties.getMqtt();
        MqttClient client = null;
        try {
            // 必须显式用 MemoryPersistence：
            // 两参数的 new MqttClient(broker, clientId) 会用 MqttDefaultFilePersistence，
            // 在当前工作目录下建 JavaService-* 子目录保存会话。服务器上进程以 www 运行、
            // 工作目录属主是 root，建目录失败就抛 MqttPersistenceException，
            // 表现为"连不上 broker"，其实连网络都没碰。
            client = new MqttClient(mqtt.getBroker(), mqtt.getClientId(), new MemoryPersistence());
            client.setCallback(buildCallback());
            client.connect(buildOptions(mqtt));
            client.subscribe(mqtt.getTopic());
            mqttClient = client;
            log.info("[MQTT] 已连接 {}（clientId={}），订阅主题: {}",
                    mqtt.getBroker(), mqtt.getClientId(), mqtt.getTopic());
        } catch (Exception e) {
            closeQuietly(client);
            logConnectFailure(mqtt, e);
        }
    }

    private MqttConnectOptions buildOptions(PlatformProperties.Mqtt mqtt) {
        MqttConnectOptions options = new MqttConnectOptions();
        options.setCleanSession(true);
        options.setAutomaticReconnect(true);
        options.setConnectionTimeout(CONNECTION_TIMEOUT_SECONDS);
        options.setKeepAliveInterval(KEEP_ALIVE_SECONDS);
        // EMQX 开启认证后必须带账号密码；留空则按匿名连接。
        String username = mqtt.getUsername();
        if (username != null && !username.isBlank()) {
            options.setUserName(username);
            options.setPassword(mqtt.getPassword() == null ? new char[0] : mqtt.getPassword().toCharArray());
        }
        return options;
    }

    private MqttCallback buildCallback() {
        return new MqttCallback() {
            @Override
            public void connectionLost(Throwable cause) {
                log.warn("[MQTT] 连接断开（客户端将自动重连）: {}", describe(cause));
            }

            @Override
            public void messageArrived(String arrivedTopic, MqttMessage message) {
                updateLatest(new String(message.getPayload()));
            }

            @Override
            public void deliveryComplete(IMqttDeliveryToken token) {
                // 只订阅不发布，无需处理
            }
        };
    }

    /**
     * 连接失败日志：把 broker、clientId、Paho 的 reasonCode 和根因全部打出来。
     */
    private void logConnectFailure(PlatformProperties.Mqtt mqtt, Exception e) {
        Throwable root = rootCause(e);
        if (e instanceof MqttException mqttException) {
            log.warn("[MQTT] 连接失败 broker={} clientId={} reasonCode={} cause={}，{}s 后重试",
                    mqtt.getBroker(), mqtt.getClientId(), mqttException.getReasonCode(),
                    describe(root), RECONNECT_INTERVAL_SECONDS, mqttException);
        } else {
            log.warn("[MQTT] 连接失败 broker={} clientId={} cause={}，{}s 后重试",
                    mqtt.getBroker(), mqtt.getClientId(), describe(root),
                    RECONNECT_INTERVAL_SECONDS, e);
        }
    }

    private boolean isConnected() {
        return mqttClient != null && mqttClient.isConnected();
    }

    private static String describe(Throwable t) {
        if (t == null) {
            return "未知";
        }
        return t.getClass().getSimpleName() + (t.getMessage() == null ? "" : ": " + t.getMessage());
    }

    private static Throwable rootCause(Throwable t) {
        Throwable current = t;
        while (current.getCause() != null && current.getCause() != current) {
            current = current.getCause();
        }
        return current;
    }

    private static void closeQuietly(MqttClient client) {
        if (client == null) {
            return;
        }
        try {
            if (client.isConnected()) {
                client.disconnect();
                log.info("[MQTT] 已断开连接");
            }
        } catch (Exception e) {
            log.debug("[MQTT] 断开连接异常: {}", e.getMessage());
        }
        try {
            client.close(true);
        } catch (Exception e) {
            log.debug("[MQTT] 关闭客户端异常: {}", e.getMessage());
        }
    }

    private void startScheduledSave() {
        // 水情记录固定按「秒」落库（默认 10 秒一条）；至少 1 秒，避免配置 0 变成忙等
        long intervalSeconds = Math.max(1L, properties.getMqtt().getSaveIntervalSeconds());
        scheduler = Executors.newSingleThreadScheduledExecutor(runnable -> {
            Thread thread = new Thread(runnable, "mqtt-save");
            thread.setDaemon(true);
            return thread;
        });
        scheduler.scheduleAtFixedRate(this::saveLatest, intervalSeconds, intervalSeconds, TimeUnit.SECONDS);
        log.info("[数据库] 水情记录落库间隔：{} 秒", intervalSeconds);
    }

    /**
     * 解析上报报文：{@code {"level":.., "temp":.., "ph":.., "orp":.., "relay":[r1..r6]}}。
     *
     * <p>缺测的字段写 null 而不是 0：0 和「没有这一项」在阈值判断、统计均值里含义完全不同。
     */
    private void updateLatest(String payload) {
        try {
            JSONObject json = JSON.parseObject(payload);
            if (json == null) {
                log.warn("[MQTT] 报文为空，已忽略");
                return;
            }

            JSONArray relayArray = json.getJSONArray("relay");
            int[] relays = new int[6];
            for (int index = 0; index < relays.length; index++) {
                relays[index] = relayArray != null && relayArray.size() > index
                        ? relayArray.getIntValue(index) : 0;
            }

            WaterReading reading = new WaterReading();
            reading.setLevel(doubleValue(json, "level"));
            reading.setTemperature(doubleValue(json, "temp"));
            reading.setPh(doubleValue(json, "ph"));
            reading.setOrp(doubleValue(json, "orp"));
            reading.setRelay1(relays[0]);
            reading.setRelay2(relays[1]);
            reading.setRelay3(relays[2]);
            reading.setRelay4(relays[3]);
            reading.setRelay5(relays[4]);
            reading.setRelay6(relays[5]);
            reading.setTime(Instant.now());
            reading.setCreatedAt(Instant.now());
            reading.setSource(WaterReading.SOURCE_MQTT);

            // 四项监测值全为空：这是 RTU 的心跳/占位帧（relay 也全 0），
            // 既不该落库（会变成一条全 null 的垃圾记录），也不该参与阈值判断。
            if (reading.getLevel() == null && reading.getTemperature() == null
                    && reading.getPh() == null && reading.getOrp() == null) {
                log.debug("[MQTT] 本帧所有监测值均为空（心跳/占位帧），已忽略");
                return;
            }

            synchronized (lock) {
                latestReading = reading;
                hasNewData = true;
            }

            // 实时阈值比对：不等落库间隔，收到就算，越界立即推送
            monitor.evaluate(reading);
        } catch (Exception e) {
            log.warn("[MQTT] 报文解析失败: {}", e.getMessage());
        }
    }

    /**
     * 读取可选数值字段。
     *
     * <p>必须区分「缺测」和「真的是 0」：
     * RTU 会间歇性上报 {@code "level":null}（甚至四项全 null），
     * 而 fastjson 的 {@code getDoubleValue()} 对 JSON null 返回 0，
     * 直接用它会把空读数存成 0，还会误触发“低于下限”告警。
     * 这里显式取出原值：null / 空串 / 非数字一律返回 null（缺测）。
     */
    static Double doubleValue(JSONObject json, String key) {
        Object value = json.get(key);
        if (value == null) {
            return null;
        }
        if (value instanceof Number number) {
            double result = number.doubleValue();
            return Double.isFinite(result) ? result : null;
        }
        if (value instanceof String text) {
            String normalized = text.trim();
            if (normalized.isEmpty()) {
                return null;
            }
            try {
                double result = Double.parseDouble(normalized);
                return Double.isFinite(result) ? result : null;
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return null;
    }

    private void saveLatest() {
        WaterReading toSave;
        synchronized (lock) {
            if (!hasNewData || latestReading == null) {
                return;
            }
            toSave = latestReading;
            hasNewData = false;
        }

        waterReadingService.save(toSave);
        log.info("[数据库] 已保存水情到 MongoDB: level={} temp={}",
                toSave.getLevel(), toSave.getTemperature());
    }
}
