/*
 Navicat Premium Data Transfer

 Source Server         : Mysql80
 Source Server Type    : MySQL
 Source Server Version : 80025
 Source Host           : localhost:3306
 Source Schema         : dam

 Target Server Type    : MySQL
 Target Server Version : 80025
 File Encoding         : 65001

 Date: 20/10/2026 20:19:13
*/

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------
-- Table structure for dam_device
-- ----------------------------
DROP TABLE IF EXISTS `dam_device`;
CREATE TABLE `dam_device`  (
  `device_id` int(0) NOT NULL AUTO_INCREMENT COMMENT '设备ID',
  `dam_id` int(0) NOT NULL COMMENT '所属大坝ID',
  `device_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '设备名称',
  `device_code` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '设备编号（唯一）',
  `device_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '设备类型：水位计/渗压计/雨量计/位移计/温度传感器',
  `manufacturer` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '生产厂家',
  `model` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '设备型号',
  `install_time` datetime(0) NULL DEFAULT NULL COMMENT '安装时间',
  `install_position` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '安装位置',
  `protocol` varchar(30) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT 'MQTT' COMMENT '通信协议：MQTT/Modbus/4G/NB-IoT',
  `status` tinyint(0) NULL DEFAULT 1 COMMENT '状态：1=在线 2=离线 3=故障 0=禁用',
  `create_time` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `update_time` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0) ON UPDATE CURRENT_TIMESTAMP(0),
  `remark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (`device_id`) USING BTREE,
  UNIQUE INDEX `device_code`(`device_code`) USING BTREE,
  INDEX `idx_dam_id`(`dam_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 2 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '监测设备表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of dam_device
-- ----------------------------

-- ----------------------------
-- Table structure for dam_info
-- ----------------------------
DROP TABLE IF EXISTS `dam_info`;
CREATE TABLE `dam_info`  (
  `dam_id` int(0) NOT NULL AUTO_INCREMENT COMMENT '大坝ID',
  `dam_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '大坝名称',
  `dam_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '大坝类型(土石坝/混凝土坝/拱坝)',
  `river_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '所在河流',
  `location` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '地理位置',
  `design_water_level` decimal(10, 2) NULL DEFAULT NULL COMMENT '设计水位(m)',
  `die_water_level` decimal(10, 2) NULL DEFAULT NULL COMMENT '死水位(m)',
  `flood_water_level` decimal(10, 2) NULL DEFAULT NULL COMMENT '防洪高水位(m)',
  `dam_height` decimal(10, 2) NULL DEFAULT NULL COMMENT '坝高(m)',
  `dam_storage` decimal(10, 2) NULL DEFAULT NULL COMMENT '水库容积m³',
  `control_area` decimal(10, 2) NULL DEFAULT NULL COMMENT '控制流域面积',
  `build_year` varchar(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '建成年份',
  `status` tinyint(0) NULL DEFAULT 1 COMMENT '状态 1-正常 0-停用',
  `remark` text CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL COMMENT '备注',
  PRIMARY KEY (`dam_id`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 7 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '大坝基础信息表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of dam_info
-- ----------------------------

-- ----------------------------
-- Table structure for dam_system_param
-- ----------------------------
DROP TABLE IF EXISTS `dam_system_param`;
CREATE TABLE `dam_system_param`  (
  `param_id` int(0) NOT NULL AUTO_INCREMENT COMMENT '参数ID',
  `param_code` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '参数编码',
  `param_name` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '参数名称',
  `param_low_value` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '安全参数最低值',
  `param_high_value` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL COMMENT '安全参数最高值',
  `param_type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '参数类型(水位、液压、水质等)',
  `create_time` datetime(0) NULL DEFAULT CURRENT_TIMESTAMP(0),
  `remark` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL COMMENT '备注',
  PRIMARY KEY (`param_id`) USING BTREE,
  UNIQUE INDEX `param_code`(`param_code`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 8 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci COMMENT = '大坝系统运行参数表' ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of dam_system_param
-- ----------------------------
INSERT INTO `dam_system_param` VALUES (1, '10001', '水位', '20', '120', '水位值', '2026-04-24 11:07:01', NULL);
INSERT INTO `dam_system_param` VALUES (2, '10002', '水质', '0.3', '0.8', '水质值', '2026-04-24 11:08:49', NULL);
INSERT INTO `dam_system_param` VALUES (3, '10003', 'PH值', '6.1', '9', 'PH值', '2026-04-24 11:09:26', NULL);
INSERT INTO `dam_system_param` VALUES (4, 'water_level', '水位', '0.20', '1.20', '水情', '2026-10-20 16:53:01', '单位：m');
INSERT INTO `dam_system_param` VALUES (5, 'temperature', '液温', '5', '35', '水质', '2026-10-20 16:53:01', '单位：℃');
INSERT INTO `dam_system_param` VALUES (6, 'ph', 'pH', '6.50', '8.50', '水质', '2026-10-20 16:53:01', '无量纲');
INSERT INTO `dam_system_param` VALUES (7, 'orp', 'ORP', '-100', '300', '水质', '2026-10-20 16:53:01', '单位：mV');

-- ----------------------------
-- Table structure for message
-- ----------------------------
DROP TABLE IF EXISTS `message`;
CREATE TABLE `message`  (
  `id` varchar(64) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `level` int(0) NOT NULL DEFAULT 1,
  `type` varchar(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `content` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `is_read` tinyint(0) NOT NULL DEFAULT 0,
  `create_time` datetime(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_message_read_time`(`is_read`, `create_time`) USING BTREE
) ENGINE = InnoDB CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of message
-- ----------------------------

-- ----------------------------
-- Table structure for platform_audit
-- ----------------------------
DROP TABLE IF EXISTS `platform_audit`;
CREATE TABLE `platform_audit`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `username` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `action` varchar(255) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NOT NULL,
  `target_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci NULL DEFAULT NULL,
  `success` tinyint(0) NOT NULL DEFAULT 1,
  `create_time` datetime(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_audit_time`(`create_time`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 9 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of platform_audit
-- ----------------------------

-- ----------------------------
-- Table structure for user
-- ----------------------------
DROP TABLE IF EXISTS `user`;
CREATE TABLE `user`  (
  `id` int(0) NOT NULL AUTO_INCREMENT,
  `username` varchar(30) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `password` varchar(30) CHARACTER SET utf8 COLLATE utf8_unicode_ci NOT NULL,
  `level` int(0) NOT NULL,
  `update_time` int(0) NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`) USING BTREE,
  UNIQUE INDEX `username`(`username`) USING BTREE
) ENGINE = MyISAM AUTO_INCREMENT = 46 CHARACTER SET = utf8 COLLATE = utf8_unicode_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of user
-- ----------------------------
INSERT INTO `user` VALUES (1, 'admin', '123456', 0, 0);
INSERT INTO `user` VALUES (2, 'test1', 'test', 2, 0);

-- ----------------------------
-- Table structure for water_log
-- ----------------------------
DROP TABLE IF EXISTS `water_log`;
CREATE TABLE `water_log`  (
  `id` bigint(0) NOT NULL AUTO_INCREMENT,
  `level` float NULL DEFAULT NULL,
  `temperature` float NULL DEFAULT NULL,
  `relay1` int(0) NULL DEFAULT NULL,
  `relay2` int(0) NULL DEFAULT NULL,
  `relay3` int(0) NULL DEFAULT NULL,
  `relay4` int(0) NULL DEFAULT NULL,
  `relay5` int(0) NULL DEFAULT NULL,
  `relay6` int(0) NULL DEFAULT NULL,
  `ph` float NULL DEFAULT NULL,
  `orp` float NULL DEFAULT NULL,
  `time` timestamp(0) NOT NULL DEFAULT CURRENT_TIMESTAMP(0),
  PRIMARY KEY (`id`) USING BTREE,
  INDEX `idx_time`(`time`) USING BTREE
) ENGINE = InnoDB AUTO_INCREMENT = 3 CHARACTER SET = utf8mb4 COLLATE = utf8mb4_0900_ai_ci ROW_FORMAT = Dynamic;

-- ----------------------------
-- Records of water_log
-- ----------------------------

SET FOREIGN_KEY_CHECKS = 1;
