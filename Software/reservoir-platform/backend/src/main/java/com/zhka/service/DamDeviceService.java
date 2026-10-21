package com.zhka.service;

import com.zhka.entity.DamDevice;
import com.zhka.mapper.DamDeviceMapper;
import com.zhka.util.Params;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;

/** 设备台账用例。 */
@Service
public class DamDeviceService {

    private final DamDeviceMapper damDeviceMapper;

    public DamDeviceService(DamDeviceMapper damDeviceMapper) {
        this.damDeviceMapper = damDeviceMapper;
    }

    public List<DamDevice> findAll() {
        return damDeviceMapper.findAll();
    }

    /** 新增设备 */
    public void create(Map<String, String> params) {
        DamDevice device = new DamDevice();
        applyFields(device, params);
        damDeviceMapper.insert(device);
    }

    /**
     * 更新设备：只覆盖前端传入的字段。
     *
     * @return 设备不存在时返回 false
     */
    public boolean update(Integer deviceId, Map<String, String> params) {
        DamDevice existing = damDeviceMapper.findById(deviceId);
        if (existing == null) {
            return false;
        }
        applyFields(existing, params);
        damDeviceMapper.update(existing);
        return true;
    }

    public void delete(Integer deviceId) {
        damDeviceMapper.delete(deviceId);
    }

    /** 按表单参数填充实体：键不存在则不覆盖 */
    private void applyFields(DamDevice device, Map<String, String> params) {
        String deviceName = Params.text(params, "device_name");
        if (deviceName != null) {
            device.setDeviceName(deviceName);
        }
        String deviceCode = Params.text(params, "device_code");
        if (deviceCode != null) {
            device.setDeviceCode(deviceCode);
        }
        String deviceType = Params.text(params, "device_type");
        if (deviceType != null) {
            device.setDeviceType(deviceType);
        }
        Integer damId = Params.integer(params, "dam_id");
        if (damId != null) {
            device.setDamId(damId);
        }
        String manufacturer = Params.text(params, "manufacturer");
        if (manufacturer != null) {
            device.setManufacturer(manufacturer);
        }
        String model = Params.text(params, "model");
        if (model != null) {
            device.setModel(model);
        }
        String protocol = Params.text(params, "protocol");
        if (protocol != null) {
            device.setProtocol(protocol);
        }
        Integer status = Params.integer(params, "status");
        if (status != null) {
            device.setStatus(status);
        }
        String installPosition = Params.text(params, "install_position");
        if (installPosition != null) {
            device.setInstallPosition(installPosition);
        }
        String remark = Params.text(params, "remark");
        if (remark != null) {
            device.setRemark(remark);
        }
    }
}
