package com.zhka.entity;

import java.util.Date;

/** 系统参数（监测阈值上下限），对应表 {@code dam_system_param}。 */
public class DamSystemParam {

    private Integer paramId;
    private String paramCode;
    private String paramName;
    /** 表字段为 VARCHAR，故此处保持字符串，避免前端传 "" 时解析失败 */
    private String paramLowValue;
    private String paramHighValue;
    private String paramType;
    private Date createTime;
    private String remark;

    public Integer getParamId() {
        return paramId;
    }

    public void setParamId(Integer paramId) {
        this.paramId = paramId;
    }

    public String getParamCode() {
        return paramCode;
    }

    public void setParamCode(String paramCode) {
        this.paramCode = paramCode;
    }

    public String getParamName() {
        return paramName;
    }

    public void setParamName(String paramName) {
        this.paramName = paramName;
    }

    public String getParamLowValue() {
        return paramLowValue;
    }

    public void setParamLowValue(String paramLowValue) {
        this.paramLowValue = paramLowValue;
    }

    public String getParamHighValue() {
        return paramHighValue;
    }

    public void setParamHighValue(String paramHighValue) {
        this.paramHighValue = paramHighValue;
    }

    public String getParamType() {
        return paramType;
    }

    public void setParamType(String paramType) {
        this.paramType = paramType;
    }

    public Date getCreateTime() {
        return createTime;
    }

    public void setCreateTime(Date createTime) {
        this.createTime = createTime;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }
}
