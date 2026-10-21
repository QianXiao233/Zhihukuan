package com.zhka;

import com.zhka.service.JwtService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.transaction.annotation.Transactional;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.assertj.core.api.Assertions.assertThat;

/** 显式启用的真实 MySQL 集成测试；所有测试资料与审计随事务回滚。 */
@SpringBootTest(properties={"reservoir.platform.mqtt.enabled=false", "reservoir.push.enabled=false", "reservoir.asr.enabled=false"})
@AutoConfigureMockMvc
@Transactional
@EnabledIfEnvironmentVariable(named="MANAGEMENT_DB_TEST", matches="true")
class ManagementIntegrationTest {
    @Autowired MockMvc mvc;
    @Autowired JdbcTemplate jdbc;
    @Autowired JwtService jwt;
    private String header(String name, int level) { return "Bearer " + jwt.generateToken(name, level); }
    @AfterEach void cleanupUsers() {
        jdbc.update("DELETE FROM user WHERE username IN ('qa_test_admin','qa_test_duty','qa_test_legacy')");
        jdbc.update("DELETE FROM message WHERE content='QA测试通知'");
        jdbc.update("DELETE FROM dam_device WHERE device_code='qa-test-device'");
        jdbc.update("DELETE FROM dam_info WHERE dam_name='QA测试水库'");
    }
    @BeforeEach void users() {
        cleanupUsers();
        jdbc.update("INSERT INTO dam_info(dam_name,status) VALUES ('QA测试水库',1)");
        jdbc.update("INSERT INTO user(username,password,level) VALUES ('qa_test_admin','testing123',3),('qa_test_duty','testing123',1),('qa_test_legacy','testing123',0)");
    }
    @Test void enforcesDatabaseRoleEvenWithElevatedTokenClaim() throws Exception {
        mvc.perform(post("/api/manage/device/add").header("Authorization", header("qa_test_duty",3)).param("device_name","denied"))
            .andExpect(status().isForbidden());
        mvc.perform(get("/api/manage/user/list")).andExpect(status().isUnauthorized());
    }
    @Test void legacyAdminCanListUsersWithoutPasswordLeak() throws Exception {
        mvc.perform(get("/api/manage/user/list").header("Authorization",header("qa_test_legacy",0)))
            .andExpect(status().isOk()).andExpect(jsonPath("$.success").value(true))
            .andExpect(jsonPath("$.data[*].password").doesNotExist());
    }
    @Test void savesDeviceAndRecordsAuditWithoutPassword() throws Exception {
        mvc.perform(post("/api/manage/device/add").header("Authorization",header("qa_test_admin",3))
            .param("dam_id",String.valueOf(jdbc.queryForObject("SELECT dam_id FROM dam_info WHERE dam_name='QA测试水库'",Integer.class)))
            .param("device_name","QA闸门").param("device_code","qa-test-device").param("status","1"))
            .andExpect(jsonPath("$.success").value(true));
        assertThat(jdbc.queryForObject("SELECT device_name FROM dam_device WHERE device_code='qa-test-device'",String.class)).isEqualTo("QA闸门");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM platform_audit WHERE username='qa_test_admin'",Integer.class)).isEqualTo(1);
    }
    @Test void blankPasswordPreservesExistingAndSelfDeletionIsDenied() throws Exception {
        int id=jdbc.queryForObject("SELECT id FROM user WHERE username='qa_test_duty'",Integer.class);
        mvc.perform(post("/api/manage/user/update").header("Authorization",header("qa_test_admin",3))
            .param("id",String.valueOf(id)).param("username","qa_test_duty").param("password","").param("level","2"))
            .andExpect(jsonPath("$.success").value(true));
        assertThat(jdbc.queryForObject("SELECT password FROM user WHERE id=?",String.class,id)).isEqualTo("testing123");
        int admin=jdbc.queryForObject("SELECT id FROM user WHERE username='qa_test_admin'",Integer.class);
        mvc.perform(post("/api/manage/user/delete").header("Authorization",header("qa_test_admin",3)).param("id",String.valueOf(admin)))
            .andExpect(jsonPath("$.success").value(false));
    }
    @Test void filtersAndExportsAllSixRelaysAndRejectsReversedRange() throws Exception {
        jdbc.update("INSERT INTO water_log(level,temperature,ph,orp,relay1,relay2,relay3,relay4,relay5,relay6,time) VALUES (0.3,29.4,7.94,84,0,0,0,0,1,1,'2020-01-02 00:00:00')");
        String token=header("qa_test_admin",3);
        mvc.perform(get("/api/manage/data/summary").header("Authorization",token).param("start","2020-01-01 00:00:00").param("end","2020-01-03 00:00:00"))
            .andExpect(jsonPath("$.data.count").value(1)).andExpect(jsonPath("$.data.recent[0].relay6").value(1));
        mvc.perform(get("/api/manage/data/export").header("Authorization",token).param("start","2020-01-01 00:00:00").param("end","2020-01-03 00:00:00"))
            .andExpect(status().isOk()).andExpect(content().string(org.hamcrest.Matchers.containsString("闸门6")));
        mvc.perform(get("/api/manage/data/summary").header("Authorization",token).param("start","2020-01-03 00:00:00").param("end","2020-01-01 00:00:00"))
            .andExpect(status().isBadRequest());
    }
    @Test void messageReadAliasAndRuntimeQueriesExecuteOnMysql() throws Exception {
        mvc.perform(get("/api/get_messagelist")).andExpect(status().isOk()).andExpect(jsonPath("$.messagelist").isArray());
        mvc.perform(get("/api/manage/runtime").header("Authorization",header("qa_test_admin",3)))
            .andExpect(jsonPath("$.data.database").value(true));
    }
    @Test void notificationManagementRequiresLoginAndHonorsDutyRole() throws Exception {
        mvc.perform(get("/api/manage/messages/list")).andExpect(status().isUnauthorized());
        mvc.perform(post("/api/manage/messages/add").header("Authorization",header("qa_test_duty",1))
            .param("level","2").param("type","QA").param("content","QA测试通知"))
            .andExpect(status().isForbidden());
        mvc.perform(post("/api/manage/messages/add").header("Authorization",header("qa_test_admin",3))
            .param("level","2").param("type","QA").param("content","QA测试通知"))
            .andExpect(jsonPath("$.success").value(true));
        String id=jdbc.queryForObject("SELECT id FROM message WHERE content='QA测试通知'",String.class);
        mvc.perform(get("/api/manage/messages/list").header("Authorization",header("qa_test_duty",1)))
            .andExpect(status().isOk()).andExpect(jsonPath("$.data[?(@.content=='QA测试通知')]" ).isNotEmpty());
        mvc.perform(post("/api/manage/messages/read").header("Authorization",header("qa_test_duty",1)).param("id",id))
            .andExpect(jsonPath("$.success").value(true));
        mvc.perform(post("/api/manage/messages/delete").header("Authorization",header("qa_test_duty",1)).param("id",id))
            .andExpect(status().isForbidden());
    }

    @Test void acceptsLargeDamStorageAfterSchemaUpgrade() throws Exception {
        mvc.perform(post("/api/manage/dam/add").header("Authorization",header("qa_test_admin",3))
            .param("dam_name","QA大库容水库").param("dam_storage","12000000.50").param("control_area","25000.75"))
            .andExpect(jsonPath("$.success").value(true));
        assertThat(jdbc.queryForObject("SELECT dam_storage FROM dam_info WHERE dam_name='QA大库容水库'", java.math.BigDecimal.class))
            .isEqualByComparingTo("12000000.50");
        jdbc.update("DELETE FROM dam_info WHERE dam_name='QA大库容水库'");
    }

    @Test void updatesDamArchiveFields() throws Exception {
        int damId = jdbc.queryForObject("SELECT dam_id FROM dam_info WHERE dam_name='QA测试水库'", Integer.class);
        mvc.perform(post("/api/manage/dam/update").header("Authorization", header("qa_test_admin", 3))
            .param("dam_id", String.valueOf(damId))
            .param("dam_name", "QA测试水库已更新")
            .param("dam_type", "中型")
            .param("river_name", "测试河流")
            .param("design_water_level", "128.50")
            .param("status", "0"))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.success").value(true))
            .andExpect(jsonPath("$.message").value("更新成功"));

        assertThat(jdbc.queryForObject("SELECT dam_name FROM dam_info WHERE dam_id=?", String.class, damId))
            .isEqualTo("QA测试水库已更新");
        assertThat(jdbc.queryForObject("SELECT design_water_level FROM dam_info WHERE dam_id=?", java.math.BigDecimal.class, damId))
            .isEqualByComparingTo("128.50");
        assertThat(jdbc.queryForObject("SELECT status FROM dam_info WHERE dam_id=?", Integer.class, damId))
            .isZero();
    }
}
