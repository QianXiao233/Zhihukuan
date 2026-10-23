package com.zhka.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.ByteArrayInputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.time.Duration;
import java.time.LocalDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.GZIPInputStream;

/**
 * 和风天气实时天气 + 当日温度区间。
 *
 * <p>认证使用 QWeather 推荐的 JWT（EdDSA / Ed25519）：
 * header {@code {alg:EdDSA,kid}}，payload {@code {iss,sub,iat,exp}}，
 * 私钥只从服务器文件读取，不进入配置文件和仓库。
 *
 * <p>接口结果缓存 10 分钟，失败时如果有旧数据就返回旧数据，避免首页天气闪烁。
 */
@Service
public class WeatherService {

    private static final Logger log = LoggerFactory.getLogger(WeatherService.class);
    private static final long CACHE_MILLIS = 10 * 60 * 1000L;
    private static final DateTimeFormatter TIME_FORMAT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");

    private final ObjectMapper json;
    private final HttpClient http = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    @Value("${QWEATHER_KID:KNPKFD27V7}")
    private String kid;
    @Value("${QWEATHER_ISSUER:Q0648C02D0}")
    private String issuer;
    @Value("${QWEATHER_SUBJECT:3HTJ6YD6A4}")
    private String subject;
    @Value("${QWEATHER_PRIVATE_KEY_PATH:/www/wwwroot/zhka/backend/dam-server/secrets/qweather-ed25519-private.pem}")
    private String privateKeyPath;
    @Value("${QWEATHER_API_HOST:https://devapi.qweather.com}")
    private String apiHost;
    @Value("${QWEATHER_LATITUDE:37.40}")
    private String latitude;
    @Value("${QWEATHER_LONGITUDE:121.20}")
    private String longitude;

    private volatile PrivateKey privateKey;
    private volatile Map<String, Object> cached;
    private volatile long cachedAt;

    public WeatherService(ObjectMapper json) {
        this.json = json;
    }

    public Map<String, Object> current() {
        long now = System.currentTimeMillis();
        Map<String, Object> snapshot = cached;
        if (snapshot != null && now - cachedAt < CACHE_MILLIS) {
            return snapshot;
        }
        synchronized (this) {
            now = System.currentTimeMillis();
            if (cached != null && now - cachedAt < CACHE_MILLIS) {
                return cached;
            }
            try {
                Map<String, Object> data = fetch();
                cached = data;
                cachedAt = now;
                return data;
            } catch (Exception ex) {
                if (cached != null) {
                    Map<String, Object> stale = new LinkedHashMap<>(cached);
                    stale.put("stale", true);
                    stale.put("message", ex.getMessage());
                    return stale;
                }
                throw new IllegalStateException(ex.getMessage(), ex);
            }
        }
    }

    private Map<String, Object> fetch() throws Exception {
        if (isBlank(kid) || isBlank(issuer) || isBlank(subject) || isBlank(privateKeyPath)) {
            throw new IllegalStateException("天气服务未配置完整");
        }
        String host = normalizeHost(apiHost);
        String token = jwt();

        Map<String, Object> current = getJson(host + "/weather/v1/current/" + latitude + "/" + longitude
                + "?localTime=true&lang=zh", token);
        Map<String, Object> daily = null;
        try {
            daily = getJson(host + "/weather/v1/daily/" + latitude + "/" + longitude
                    + "?days=1&localTime=true&lang=zh", token);
        } catch (Exception ex) {
            log.warn("天气每日预报获取失败，仅展示实时温度: {}", ex.getMessage());
        }

        Map<String, Object> condition = map(current.get("condition"));
        Map<String, Object> temperature = map(current.get("temperature"));
        Map<String, Object> wind = map(current.get("wind"));
        Map<String, Object> direction = map(wind.get("direction"));
        Map<String, Object> feelsLike = map(current.get("feelsLike"));
        Map<String, Object> pressure = map(current.get("pressure"));
        Map<String, Object> visibility = map(current.get("visibility"));
        Map<String, Object> precipitation = map(current.get("precipitation"));
        Map<String, Object> precipitationAmount = map(precipitation.get("amount"));
        Map<String, Object> windSpeed = map(wind.get("speed"));
        Map<String, Object> windGust = map(current.get("windGust"));

        Double temp = number(temperature.get("value"));
        Double tempMax = null;
        Double tempMin = null;
        Double precipProbability = null;
        String dailyText = "";
        String dayText = "";
        String nightText = "";
        String sunrise = "";
        String sunset = "";
        if (daily != null && daily.get("days") instanceof List<?> days && !days.isEmpty()) {
            Map<String, Object> day = map(days.get(0));
            tempMax = number(map(day.get("temperatureMax")).get("value"));
            tempMin = number(map(day.get("temperatureMin")).get("value"));
            Map<String, Object> daytime = map(day.get("daytime"));
            Map<String, Object> nighttime = map(day.get("nighttime"));
            Map<String, Object> astro = map(day.get("astro"));
            dailyText = text(map(daytime.get("condition")).get("text"));
            dayText = dailyText;
            nightText = text(map(nighttime.get("condition")).get("text"));
            sunrise = text(astro.get("sunrise"));
            sunset = text(astro.get("sunset"));
            precipProbability = number(map(daytime.get("precipitation")).get("probability"));
        }

        String text = text(condition.get("text"));
        if (text.isEmpty()) {
            text = dailyText;
        }
        if (text.isEmpty()) {
            text = "天气";
        }

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("text", text);
        data.put("icon", text(condition.get("code")));
        data.put("temp", round(temp, 1));
        data.put("tempMax", round(tempMax, 0));
        data.put("tempMin", round(tempMin, 0));
        data.put("windDir", windName(text(direction.get("compass"))));
        data.put("windScale", round(number(wind.get("scale")), 0));
        data.put("windSpeed", round(number(windSpeed.get("value")), 1));
        data.put("windGust", round(number(windGust.get("value")), 1));
        data.put("humidity", round(number(current.get("humidity")) == null ? null : number(current.get("humidity")) * 100, 0));
        data.put("feelsLike", round(number(feelsLike.get("value")), 1));
        data.put("pressure", round(number(pressure.get("value")), 0));
        data.put("visibilityKm", round(number(visibility.get("value")) == null ? null : number(visibility.get("value")) / 1000, 1));
        data.put("precipitation", round(number(precipitationAmount.get("value")), 1));
        data.put("precipitationType", text(precipitation.get("type")));
        data.put("precipProbability", round(precipProbability == null ? null : precipProbability * 100, 0));
        data.put("uvIndex", round(number(current.get("uvIndex")), 0));
        data.put("cloudCover", round(number(current.get("cloudCover")) == null ? null : number(current.get("cloudCover")) * 100, 0));
        data.put("sunrise", sunrise);
        data.put("sunset", sunset);
        data.put("dayText", dayText);
        data.put("nightText", nightText);
        data.put("observedAt", LocalDateTime.now(ZoneOffset.ofHours(8)).format(TIME_FORMAT));
        data.put("stale", false);
        return data;
    }

    private Map<String, Object> getJson(String url, String token) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create(url))
                .timeout(Duration.ofSeconds(10))
                .header("Authorization", "Bearer " + token)
                .header("Accept-Encoding", "gzip")
                .header("Accept", "application/json")
                .GET()
                .build();
        HttpResponse<byte[]> response = http.send(request, HttpResponse.BodyHandlers.ofByteArray());
        byte[] bytes = response.body() == null ? new byte[0] : response.body();
        // QWeather 有时忽略 identity 直接返回 gzip，这里手动解压。
        if (bytes.length >= 2 && (bytes[0] & 0xff) == 0x1f && (bytes[1] & 0xff) == 0x8b) {
            try (GZIPInputStream gzip = new GZIPInputStream(new ByteArrayInputStream(bytes))) {
                bytes = gzip.readAllBytes();
            }
        }
        String body = new String(bytes, StandardCharsets.UTF_8);
        if (response.statusCode() != 200) {
            String detail = body == null ? "" : body.replaceAll("\\s+", " ").trim();
            if (detail.length() > 180) {
                detail = detail.substring(0, 180);
            }
            throw new IllegalStateException("天气接口返回 " + response.statusCode()
                    + (detail.isEmpty() ? "" : "：" + detail));
        }
        return json.readValue(body, Map.class);
    }

    private String jwt() throws Exception {
        long iat = System.currentTimeMillis() / 1000 - 30;
        long exp = iat + 900;
        String header = json.writeValueAsString(Map.of("alg", "EdDSA", "kid", kid));
        String payload = json.writeValueAsString(Map.of(
                "iss", issuer,
                "sub", subject,
                "iat", iat,
                "exp", exp));
        Base64.Encoder encoder = Base64.getUrlEncoder().withoutPadding();
        String data = encoder.encodeToString(header.getBytes(StandardCharsets.UTF_8))
                + "." + encoder.encodeToString(payload.getBytes(StandardCharsets.UTF_8));
        Signature signer = Signature.getInstance("EdDSA");
        signer.initSign(privateKey());
        signer.update(data.getBytes(StandardCharsets.UTF_8));
        return data + "." + encoder.encodeToString(signer.sign());
    }

    private PrivateKey privateKey() throws Exception {
        PrivateKey existing = privateKey;
        if (existing != null) {
            return existing;
        }
        synchronized (this) {
            if (privateKey != null) {
                return privateKey;
            }
            String pem = Files.readString(Path.of(privateKeyPath), StandardCharsets.UTF_8);
            String base64 = pem
                    .replace("-----BEGIN PRIVATE KEY-----", "")
                    .replace("-----END PRIVATE KEY-----", "")
                    .replaceAll("\\s+", "");
            byte[] der = Base64.getDecoder().decode(base64);
            privateKey = KeyFactory.getInstance("EdDSA").generatePrivate(new PKCS8EncodedKeySpec(der));
            return privateKey;
        }
    }

    private static String normalizeHost(String value) {
        String host = value == null ? "" : value.trim();
        if (host.isEmpty()) {
            host = "https://devapi.qweather.com";
        }
        if (!host.startsWith("http://") && !host.startsWith("https://")) {
            host = "https://" + host;
        }
        while (host.endsWith("/")) {
            host = host.substring(0, host.length() - 1);
        }
        return host;
    }

    private static String windName(String compass) {
        return switch (compass == null ? "" : compass.toLowerCase()) {
            case "n" -> "北风";
            case "nne" -> "东北偏北风";
            case "ne" -> "东北风";
            case "ene" -> "东北偏东风";
            case "e" -> "东风";
            case "ese" -> "东南偏东风";
            case "se" -> "东南风";
            case "sse" -> "东南偏南风";
            case "s" -> "南风";
            case "ssw" -> "西南偏南风";
            case "sw" -> "西南风";
            case "wsw" -> "西南偏西风";
            case "w" -> "西风";
            case "wnw" -> "西北偏西风";
            case "nw" -> "西北风";
            case "nnw" -> "西北偏北风";
            default -> "";
        };
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> map(Object value) {
        return value instanceof Map<?, ?> ? (Map<String, Object>) value : Map.of();
    }

    private static String text(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private static Double number(Object value) {
        if (value instanceof Number n) {
            return n.doubleValue();
        }
        if (value == null) {
            return null;
        }
        try {
            return Double.parseDouble(String.valueOf(value));
        } catch (NumberFormatException ex) {
            return null;
        }
    }

    private static Double round(Double value, int digits) {
        if (value == null) {
            return null;
        }
        double factor = Math.pow(10, digits);
        return Math.round(value * factor) / factor;
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
