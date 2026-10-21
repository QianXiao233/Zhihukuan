package com.zhka.service;

import com.zhka.entity.DamInfo;
import com.zhka.mapper.DamInfoMapper;
import com.zhka.util.Params;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/**
 * 大坝基础信息用例。
 *
 * <p>新增与更新共用 {@link #applyFields}，避免两处重复维护同一份字段映射。
 */
@Service
public class DamInfoService {

    private final DamInfoMapper damInfoMapper;

    public DamInfoService(DamInfoMapper damInfoMapper) {
        this.damInfoMapper = damInfoMapper;
    }

    public List<DamInfo> findAll() {
        return damInfoMapper.findAll();
    }

    /** 新增大坝 */
    public void create(Map<String, String> params) {
        DamInfo dam = new DamInfo();
        applyFields(dam, params);
        damInfoMapper.insert(dam);
    }

    /**
     * 更新大坝：只覆盖前端传入的字段，未传的保留原值。
     *
     * @return 大坝不存在时返回 false
     */
    public boolean update(Integer damId, Map<String, String> params) {
        DamInfo existing = damInfoMapper.findById(damId);
        if (existing == null) {
            return false;
        }
        applyFields(existing, params);
        damInfoMapper.update(existing);
        return true;
    }

    public void delete(Integer damId) {
        damInfoMapper.delete(damId);
    }

    /** 按表单参数填充实体：键不存在则不覆盖 */
    private void applyFields(DamInfo dam, Map<String, String> params) {
        String damName = Params.text(params, "dam_name");
        if (damName != null) {
            dam.setDamName(damName);
        }
        String damType = Params.text(params, "dam_type");
        if (damType != null) {
            dam.setDamType(damType);
        }
        String riverName = Params.text(params, "river_name");
        if (riverName != null) {
            dam.setRiverName(riverName);
        }
        String location = Params.text(params, "location");
        if (location != null) {
            dam.setLocation(location);
        }
        BigDecimal designWaterLevel = Params.decimal(params, "design_water_level");
        if (designWaterLevel != null) {
            dam.setDesignWaterLevel(designWaterLevel);
        }
        BigDecimal dieWaterLevel = Params.decimal(params, "die_water_level");
        if (dieWaterLevel != null) {
            dam.setDieWaterLevel(dieWaterLevel);
        }
        BigDecimal floodWaterLevel = Params.decimal(params, "flood_water_level");
        if (floodWaterLevel != null) {
            dam.setFloodWaterLevel(floodWaterLevel);
        }
        BigDecimal damHeight = Params.decimal(params, "dam_height");
        if (damHeight != null) {
            dam.setDamHeight(damHeight);
        }
        BigDecimal damStorage = Params.decimal(params, "dam_storage");
        if (damStorage != null) {
            dam.setDamStorage(damStorage);
        }
        BigDecimal controlArea = Params.decimal(params, "control_area");
        if (controlArea != null) {
            dam.setControlArea(controlArea);
        }
        String buildYear = Params.text(params, "build_year");
        if (buildYear != null) {
            dam.setBuildYear(buildYear);
        }
        Integer status = Params.integer(params, "status");
        if (status != null) {
            dam.setStatus(status);
        }
        String remark = Params.text(params, "remark");
        if (remark != null) {
            dam.setRemark(remark);
        }
    }
}
