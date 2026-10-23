package com.zhka.controller;

import com.zhka.common.ApiResult;
import com.zhka.service.WeatherService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/** 首页数字孪生天气：和风天气 JWT 认证，后端缓存后给前端。 */
@RestController
@RequestMapping("/api/weather")
public class WeatherController {

    private final WeatherService weather;

    public WeatherController(WeatherService weather) {
        this.weather = weather;
    }

    @GetMapping("/now")
    public Map<String, Object> now() {
        try {
            return ApiResult.success().data(weather.current()).toMap();
        } catch (Exception ex) {
            return ApiResult.failure(ex.getMessage() == null ? "天气获取失败" : ex.getMessage()).toMap();
        }
    }
}
