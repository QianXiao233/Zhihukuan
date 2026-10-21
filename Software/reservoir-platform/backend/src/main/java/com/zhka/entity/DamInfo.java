package com.zhka.entity;

import java.math.BigDecimal;

/** 大坝基础信息，对应表 {@code dam_info}。 */
public class DamInfo {

    private Integer damId;
    private String damName;
    private String damType;
    private String riverName;
    private String location;
    /** 设计水位 */
    private BigDecimal designWaterLevel;
    /** 死水位 */
    private BigDecimal dieWaterLevel;
    /** 汛限水位 */
    private BigDecimal floodWaterLevel;
    private BigDecimal damHeight;
    private BigDecimal damStorage;
    private BigDecimal controlArea;
    private String buildYear;
    private Integer status;
    private String remark;

    public Integer getDamId() {
        return damId;
    }

    public void setDamId(Integer damId) {
        this.damId = damId;
    }

    public String getDamName() {
        return damName;
    }

    public void setDamName(String damName) {
        this.damName = damName;
    }

    public String getDamType() {
        return damType;
    }

    public void setDamType(String damType) {
        this.damType = damType;
    }

    public String getRiverName() {
        return riverName;
    }

    public void setRiverName(String riverName) {
        this.riverName = riverName;
    }

    public String getLocation() {
        return location;
    }

    public void setLocation(String location) {
        this.location = location;
    }

    public BigDecimal getDesignWaterLevel() {
        return designWaterLevel;
    }

    public void setDesignWaterLevel(BigDecimal designWaterLevel) {
        this.designWaterLevel = designWaterLevel;
    }

    public BigDecimal getDieWaterLevel() {
        return dieWaterLevel;
    }

    public void setDieWaterLevel(BigDecimal dieWaterLevel) {
        this.dieWaterLevel = dieWaterLevel;
    }

    public BigDecimal getFloodWaterLevel() {
        return floodWaterLevel;
    }

    public void setFloodWaterLevel(BigDecimal floodWaterLevel) {
        this.floodWaterLevel = floodWaterLevel;
    }

    public BigDecimal getDamHeight() {
        return damHeight;
    }

    public void setDamHeight(BigDecimal damHeight) {
        this.damHeight = damHeight;
    }

    public BigDecimal getDamStorage() {
        return damStorage;
    }

    public void setDamStorage(BigDecimal damStorage) {
        this.damStorage = damStorage;
    }

    public BigDecimal getControlArea() {
        return controlArea;
    }

    public void setControlArea(BigDecimal controlArea) {
        this.controlArea = controlArea;
    }

    public String getBuildYear() {
        return buildYear;
    }

    public void setBuildYear(String buildYear) {
        this.buildYear = buildYear;
    }

    public Integer getStatus() {
        return status;
    }

    public void setStatus(Integer status) {
        this.status = status;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }
}
