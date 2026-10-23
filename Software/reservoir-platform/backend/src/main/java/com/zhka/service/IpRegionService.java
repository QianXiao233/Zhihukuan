package com.zhka.service;

import org.lionsoul.ip2region.xdb.Searcher;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.io.ClassPathResource;
import org.springframework.stereotype.Service;

import java.io.InputStream;
import java.util.concurrent.ConcurrentHashMap;
import java.util.Map;

/**
 * 离线 IP 归属地（省市）。
 *
 * <p>登录日志、管理审计需要显示来源地区。这里用 ip2region 的 IPv4 离线库，
 * 不调用外部接口，内网/断网也能用；私有地址统一显示“内网”。
 */
@Service
public class IpRegionService {

    private static final Logger log = LoggerFactory.getLogger(IpRegionService.class);
    private static final String DB_RESOURCE = "ip2region_v4.xdb";

    private final Searcher searcher;
    private final Map<String, String> cache = new ConcurrentHashMap<>();

    public IpRegionService() {
        Searcher loaded = null;
        try (InputStream in = new ClassPathResource(DB_RESOURCE).getInputStream()) {
            loaded = Searcher.newWithBuffer(in.readAllBytes());
        } catch (Exception ex) {
            log.warn("IP 归属地库加载失败，来源地区将留空: {}", ex.getMessage());
        }
        this.searcher = loaded;
    }

    /** 返回“山东省烟台市”这类地区；取不到时返回空串。 */
    public String resolve(String ip) {
        if (ip == null || ip.isBlank()) {
            return "";
        }
        String value = ip.trim();
        if (isPrivate(value)) {
            return "内网";
        }
        if (searcher == null) {
            return "";
        }
        return cache.computeIfAbsent(value, this::lookup);
    }

    private String lookup(String ip) {
        try {
            String region = searcher.search(ip);
            if (region == null || region.isBlank()) {
                return "";
            }
            String[] parts = region.split("\\|", -1);
            if (parts.length < 3) {
                return "";
            }
            // ip2region_v4.xdb 是“国家|省份|城市|ISP|国家码”；老 v2 库多一个“区域”字段（通常为 0）。
            int provinceIndex = "0".equals(parts[1].trim()) ? 2 : 1;
            int cityIndex = provinceIndex + 1;
            if (parts.length <= cityIndex) {
                return "";
            }
            String country = clean(parts[0]);
            String province = clean(parts[provinceIndex]);
            String city = clean(parts[cityIndex]);
            if ("中国".equals(country)) {
                if (city.isEmpty()) {
                    return province;
                }
                if (province.isEmpty() || city.equals(province)) {
                    return city;
                }
                return province + city;
            }
            if (country.isEmpty()) {
                return "";
            }
            return city.isEmpty() ? country : country + city;
        } catch (Exception ex) {
            return "";
        }
    }

    private static String clean(String value) {
        String text = value == null ? "" : value.trim();
        return "0".equals(text) ? "" : text;
    }

    private static boolean isPrivate(String ip) {
        if (ip.indexOf(':') >= 0) {
            String lower = ip.toLowerCase();
            return "::1".equals(lower) || lower.startsWith("fc") || lower.startsWith("fd")
                    || lower.startsWith("fe80:");
        }
        if (ip.startsWith("10.") || ip.startsWith("127.") || ip.startsWith("192.168.")
                || ip.startsWith("169.254.")) {
            return true;
        }
        if (ip.startsWith("172.")) {
            String[] parts = ip.split("\\.");
            if (parts.length >= 2) {
                try {
                    int second = Integer.parseInt(parts[1]);
                    return second >= 16 && second <= 31;
                } catch (NumberFormatException ignored) {
                    return false;
                }
            }
        }
        return false;
    }
}
