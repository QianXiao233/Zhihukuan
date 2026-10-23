package com.zhka.service;

import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;

class IpRegionServiceTest {

    private final IpRegionService service = new IpRegionService();

    @Test
    void privateAddressIsInternal() {
        assertEquals("内网", service.resolve("192.168.1.10"));
        assertEquals("内网", service.resolve("127.0.0.1"));
    }

    @Test
    void resolvesPublicCity() {
        String region = service.resolve("202.194.175.2");
        assertEquals("山东省烟台市", region);
    }
}
