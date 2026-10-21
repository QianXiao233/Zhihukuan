package com.zhka.util;

import java.math.BigDecimal;
import java.util.Map;

/**
 * 表单参数（{@code @RequestParam Map<String, String>}）读取工具。
 *
 * <p>统一收敛「字段存在才覆盖」的语义，并把空串 / 非法数字视为「未传」，
 * 避免前端传空串时抛 {@code NumberFormatException}。
 */
public final class Params {

    private Params() {
    }

    /** 取字符串：键存在即返回（可能是空串），不存在返回 null */
    public static String text(Map<String, String> params, String key) {
        return params.containsKey(key) ? params.get(key) : null;
    }

    /** 取小数：键不存在或值为空白时返回 null */
    public static BigDecimal decimal(Map<String, String> params, String key) {
        String value = text(params, key);
        if (value == null || value.isBlank()) {
            return null;
        }
        return new BigDecimal(value.trim());
    }

    /** 取整数：键不存在、值为空白或格式非法时返回 null */
    public static Integer integer(Map<String, String> params, String key) {
        String value = text(params, key);
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return Integer.valueOf(value.trim());
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /** 取整数（必填）：缺失时抛出带字段名的参数异常 */
    public static int requiredInteger(Map<String, String> params, String key) {
        Integer value = integer(params, key);
        if (value == null) {
            throw new IllegalArgumentException("缺少参数：" + key);
        }
        return value;
    }
}
