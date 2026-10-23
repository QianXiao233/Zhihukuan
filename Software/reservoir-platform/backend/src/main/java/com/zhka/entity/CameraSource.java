package com.zhka.entity;

import java.util.Date;

/**
 * 监控画面来源，对应表 {@code camera_source}。
 *
 * <p>浏览器不能直接播放 RTSP，RTSP 源需要视频网关（MediaMTX / go2rtc 等）
 * 转封装成 WebRTC 后，再由前端通过 WHEP 播放；WebRTC 源则直接填 WHEP 地址。
 */
public class CameraSource {

    private Integer sourceId;
    private String sourceName;
    private String location;
    /** rtsp / webrtc */
    private String protocol;
    /** 摄像机原始地址：RTSP 为 rtsp://...，WebRTC 为 WHEP 地址 */
    private String sourceUrl;
    /** 可选：直接指定最终播放地址，优先于网关拼接 */
    private String playUrl;
    /** RTSP 网关基地址，例如 http://192.168.2.7:8889 */
    private String gatewayUrl;
    /** RTSP 在网关上的播放标识，例如 topcam */
    private String streamKey;
    private Integer enabled;
    private Integer sortOrder;
    /** 绑定的数字孪生标签：drowning / boat，为空表示不绑定 */
    private String twinLabel;
    private String remark;
    private Date createTime;
    private Date updateTime;

    public Integer getSourceId() {
        return sourceId;
    }

    public void setSourceId(Integer sourceId) {
        this.sourceId = sourceId;
    }

    public String getSourceName() {
        return sourceName;
    }

    public void setSourceName(String sourceName) {
        this.sourceName = sourceName;
    }

    public String getLocation() {
        return location;
    }

    public void setLocation(String location) {
        this.location = location;
    }

    public String getProtocol() {
        return protocol;
    }

    public void setProtocol(String protocol) {
        this.protocol = protocol;
    }

    public String getSourceUrl() {
        return sourceUrl;
    }

    public void setSourceUrl(String sourceUrl) {
        this.sourceUrl = sourceUrl;
    }

    public String getPlayUrl() {
        return playUrl;
    }

    public void setPlayUrl(String playUrl) {
        this.playUrl = playUrl;
    }

    public String getGatewayUrl() {
        return gatewayUrl;
    }

    public void setGatewayUrl(String gatewayUrl) {
        this.gatewayUrl = gatewayUrl;
    }

    public String getStreamKey() {
        return streamKey;
    }

    public void setStreamKey(String streamKey) {
        this.streamKey = streamKey;
    }

    public Integer getEnabled() {
        return enabled;
    }

    public void setEnabled(Integer enabled) {
        this.enabled = enabled;
    }

    public Integer getSortOrder() {
        return sortOrder;
    }

    public void setSortOrder(Integer sortOrder) {
        this.sortOrder = sortOrder;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }

    public String getTwinLabel() {
        return twinLabel;
    }

    public void setTwinLabel(String twinLabel) {
        this.twinLabel = twinLabel;
    }

    public Date getCreateTime() {
        return createTime;
    }

    public void setCreateTime(Date createTime) {
        this.createTime = createTime;
    }

    public Date getUpdateTime() {
        return updateTime;
    }

    public void setUpdateTime(Date updateTime) {
        this.updateTime = updateTime;
    }
}
