package com.zhka.service;

import com.zhka.entity.CameraSource;
import com.zhka.mapper.CameraSourceMapper;
import com.zhka.util.Params;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/**
 * 监控画面来源用例。
 *
 * <p>管理端只负责保存「源地址 + 网关参数」，不在这里做转码；
 * RTSP 的实际播放由前端通过 WHEP 网关完成。
 */
@Service
public class CameraSourceService {

    private final CameraSourceMapper mapper;

    public CameraSourceService(CameraSourceMapper mapper) {
        this.mapper = mapper;
    }

    public List<CameraSource> findAll() {
        return mapper.findAll();
    }

    /** @return 校验失败时返回错误提示，成功返回 null */
    public String create(Map<String, String> params) {
        CameraSource source = new CameraSource();
        source.setEnabled(1);
        source.setSortOrder(100);
        applyFields(source, params);
        String error = validate(source);
        if (error != null) {
            return error;
        }
        if (source.getTwinLabel() != null) {
            mapper.clearTwinLabel(source.getTwinLabel(), 0);
        }
        mapper.insert(source);
        return null;
    }

    /** @return 校验失败 / 记录不存在时返回错误提示，成功返回 null */
    public String update(Integer sourceId, Map<String, String> params) {
        CameraSource source = mapper.findById(sourceId);
        if (source == null) {
            return "画面来源不存在";
        }
        applyFields(source, params);
        String error = validate(source);
        if (error != null) {
            return error;
        }
        if (source.getTwinLabel() != null) {
            mapper.clearTwinLabel(source.getTwinLabel(), source.getSourceId());
        }
        mapper.update(source);
        return null;
    }

    public boolean delete(Integer sourceId) {
        return mapper.delete(sourceId) > 0;
    }

    private void applyFields(CameraSource source, Map<String, String> params) {
        String sourceName = Params.text(params, "source_name");
        if (sourceName != null) {
            source.setSourceName(sourceName.trim());
        }
        String location = Params.text(params, "location");
        if (location != null) {
            source.setLocation(location.trim());
        }
        String protocol = Params.text(params, "protocol");
        if (protocol != null) {
            source.setProtocol(protocol.trim().toLowerCase());
        }
        String sourceUrl = Params.text(params, "source_url");
        if (sourceUrl != null) {
            source.setSourceUrl(sourceUrl.trim());
        }
        String playUrl = trimToNull(Params.text(params, "play_url"));
        if (params.containsKey("play_url")) {
            source.setPlayUrl(playUrl);
        }
        String gatewayUrl = trimToNull(Params.text(params, "gateway_url"));
        if (params.containsKey("gateway_url")) {
            source.setGatewayUrl(gatewayUrl);
        }
        String streamKey = trimToNull(Params.text(params, "stream_key"));
        if (params.containsKey("stream_key")) {
            source.setStreamKey(streamKey);
        }
        Integer enabled = Params.integer(params, "enabled");
        if (enabled != null) {
            source.setEnabled(enabled == 0 ? 0 : 1);
        }
        Integer sortOrder = Params.integer(params, "sort_order");
        if (sortOrder != null) {
            source.setSortOrder(Math.max(0, Math.min(9999, sortOrder)));
        }
        String remark = Params.text(params, "remark");
        if (remark != null) {
            source.setRemark(remark.trim());
        }
        String twinLabel = trimToNull(Params.text(params, "twin_label"));
        if (params.containsKey("twin_label")) {
            source.setTwinLabel(twinLabel);
        }
    }

    private String validate(CameraSource source) {
        if (isBlank(source.getSourceName())) {
            return "请输入画面名称";
        }
        if (source.getSourceName().length() > 100) {
            return "画面名称最多 100 个字符";
        }
        if (source.getLocation() != null && source.getLocation().length() > 255) {
            return "安装位置最多 255 个字符";
        }
        if (source.getRemark() != null && source.getRemark().length() > 500) {
            return "备注最多 500 个字符";
        }
        if (source.getTwinLabel() != null && !"drowning".equals(source.getTwinLabel())
                && !"boat".equals(source.getTwinLabel())) {
            return "数字孪生标签只支持 drowning 或 boat";
        }
        String protocol = source.getProtocol();
        if (!"rtsp".equals(protocol) && !"webrtc".equals(protocol)) {
            return "协议只支持 RTSP 或 WebRTC";
        }
        if (isBlank(source.getSourceUrl())) {
            return "请输入视频地址";
        }
        if (source.getSourceUrl().length() > 1000) {
            return "视频地址最多 1000 个字符";
        }
        if ("rtsp".equals(protocol)) {
            if (!source.getSourceUrl().toLowerCase().startsWith("rtsp://")) {
                return "RTSP 地址必须以 rtsp:// 开头";
            }
            if (isBlank(source.getPlayUrl()) && isBlank(source.getStreamKey())) {
                return "RTSP 画面还需填写网关播放标识（例如 topcam）";
            }
        } else if (!isHttpUrl(source.getSourceUrl())) {
            return "WebRTC 播放地址必须以 http:// 或 https:// 开头";
        }
        if (!isBlank(source.getPlayUrl()) && !isHttpUrl(source.getPlayUrl())) {
            return "覆盖播放地址必须以 http:// 或 https:// 开头";
        }
        if (!isBlank(source.getGatewayUrl()) && !isHttpUrl(source.getGatewayUrl())) {
            return "网关地址必须以 http:// 或 https:// 开头";
        }
        if (!isBlank(source.getStreamKey()) && source.getStreamKey().length() > 200) {
            return "网关播放标识最多 200 个字符";
        }
        return null;
    }

    private static boolean isHttpUrl(String value) {
        String lower = value.toLowerCase();
        return lower.startsWith("http://") || lower.startsWith("https://");
    }

    private static boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }
}
