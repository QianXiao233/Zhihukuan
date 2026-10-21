package com.zhka.dto;

import com.zhka.entity.Metric;
import com.zhka.entity.WaterReading;

import java.time.Instant;
import java.util.ArrayList;
import java.util.List;

/**
 * 水情记录的对外视图。
 *
 * <p>不直接把 {@link WaterReading} 丢给前端，是为了顺带算出「这一条有没有越界」——
 * 阈值存在 MySQL、记录存在 MongoDB，前端自己比对需要再多一次请求，
 * 而且两边的判定逻辑容易不一致。
 */
public class WaterReadingView {

    private String id;
    private Instant time;
    private Double level;
    private Double temperature;
    private Double ph;
    private Double orp;

    private Integer relay1;
    private Integer relay2;
    private Integer relay3;
    private Integer relay4;
    private Integer relay5;
    private Integer relay6;

    private String source;
    /** 越界的指标字段名（level / temperature / ph / orp），空数组表示正常 */
    private List<String> abnormalMetrics = new ArrayList<>();
    private boolean abnormal;

    public WaterReadingView() {
    }

    /** 组装视图并计算越界标记 */
    public static WaterReadingView of(WaterReading reading, Thresholds thresholds) {
        if (reading == null) {
            return null;
        }
        WaterReadingView view = new WaterReadingView();
        view.id = reading.getId();
        view.time = reading.getTime();
        view.level = reading.getLevel();
        view.temperature = reading.getTemperature();
        view.ph = reading.getPh();
        view.orp = reading.getOrp();
        view.relay1 = reading.getRelay1();
        view.relay2 = reading.getRelay2();
        view.relay3 = reading.getRelay3();
        view.relay4 = reading.getRelay4();
        view.relay5 = reading.getRelay5();
        view.relay6 = reading.getRelay6();
        view.source = reading.getSource();
        if (thresholds != null) {
            view.abnormalMetrics = new ArrayList<>(thresholds.violatedFields(reading));
            view.abnormal = !view.abnormalMetrics.isEmpty();
        }
        return view;
    }

    /** 越界指标的中文名，供 CSV / 提示文案使用 */
    public String abnormalText() {
        if (abnormalMetrics == null || abnormalMetrics.isEmpty()) {
            return "";
        }
        List<String> names = new ArrayList<>();
        for (String field : abnormalMetrics) {
            for (Metric metric : Metric.values()) {
                if (metric.field().equals(field)) {
                    names.add(metric.label());
                }
            }
        }
        return String.join("、", names);
    }

    public String getId() {
        return id;
    }

    public Instant getTime() {
        return time;
    }

    public Double getLevel() {
        return level;
    }

    public Double getTemperature() {
        return temperature;
    }

    public Double getPh() {
        return ph;
    }

    public Double getOrp() {
        return orp;
    }

    public Integer getRelay1() {
        return relay1;
    }

    public Integer getRelay2() {
        return relay2;
    }

    public Integer getRelay3() {
        return relay3;
    }

    public Integer getRelay4() {
        return relay4;
    }

    public Integer getRelay5() {
        return relay5;
    }

    public Integer getRelay6() {
        return relay6;
    }

    public String getSource() {
        return source;
    }

    public List<String> getAbnormalMetrics() {
        return abnormalMetrics;
    }

    public boolean isAbnormal() {
        return abnormal;
    }
}
