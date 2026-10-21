package com.zhka.service;

import com.zhka.entity.DamSystemParam;
import com.zhka.mapper.DamSystemParamMapper;
import com.zhka.util.Params;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/** 系统参数（监测阈值）用例。 */
@Service
public class DamSystemParamService {

    private final DamSystemParamMapper damSystemParamMapper;

    public DamSystemParamService(DamSystemParamMapper damSystemParamMapper) {
        this.damSystemParamMapper = damSystemParamMapper;
    }

    public List<DamSystemParam> findAll() {
        return damSystemParamMapper.findAll();
    }

    /** 新增参数 */
    public void create(Map<String, String> params) {
        DamSystemParam param = new DamSystemParam();
        applyFields(param, params);
        damSystemParamMapper.insert(param);
    }

    /**
     * 更新参数：只覆盖前端传入的字段。
     *
     * @return 参数不存在时返回 false
     */
    public boolean update(Integer paramId, Map<String, String> params) {
        DamSystemParam existing = damSystemParamMapper.findById(paramId);
        if (existing == null) {
            return false;
        }
        applyFields(existing, params);
        damSystemParamMapper.update(existing);
        return true;
    }

    public void delete(Integer paramId) {
        damSystemParamMapper.delete(paramId);
    }

    /** 按表单参数填充实体：键不存在则不覆盖 */
    private void applyFields(DamSystemParam param, Map<String, String> params) {
        String paramCode = Params.text(params, "param_code");
        if (paramCode != null) {
            param.setParamCode(paramCode);
        }
        String paramName = Params.text(params, "param_name");
        if (paramName != null) {
            param.setParamName(paramName);
        }
        String paramLowValue = Params.text(params, "param_low_value");
        if (paramLowValue != null) {
            param.setParamLowValue(paramLowValue);
        }
        String paramHighValue = Params.text(params, "param_high_value");
        if (paramHighValue != null) {
            param.setParamHighValue(paramHighValue);
        }
        String paramType = Params.text(params, "param_type");
        if (paramType != null) {
            param.setParamType(paramType);
        }
        String remark = Params.text(params, "remark");
        if (remark != null) {
            param.setRemark(remark);
        }
    }
}
