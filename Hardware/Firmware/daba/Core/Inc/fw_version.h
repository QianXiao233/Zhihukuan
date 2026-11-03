#ifndef __FW_VERSION_H
#define __FW_VERSION_H

/* 固件版本号 —— 发版时只改这里，屏幕标题栏右侧会自动显示
   ver 1.1：修复断网时 ETH 发送死循环（TX 死锁）、修复 60s 自动复位计时器被刷新、
            增加 e:/TX-RX 诊断
   ver 1.2：断网时不再显示旧 IP（显示 IP:-- 和 LINK DOWN），避免误判在线
   ver 1.3：完整恢复后清理 ARP 并刷新 DHCP
   ver 1.4：恢复后不再释放 IP（改为续租 dhcp_renew），干扰期间不会退化成“无 IP”
   ver 1.5：DHCP 卡住 10 秒自动重启 DHCP（连续 3 次失败则重整 ETH/PHY）
   ver 1.6：链路去抖 300ms→500ms；ETH Start_IT 失败不再把 netif 置 UP（消除假在线）
   ver 1.7：修复开机时自协商未完成就套用默认 100M 全双工（初始链路余量低、
            一次干扰就掉线）；已连上后协商结果变化会同步修正 MAC 配置 */
/* ver 2.0：撤销“只通告 100M 全双工/强制重协商”（实测协商不上），恢复标准自协商
   ver 2.1：降级到 10M/半双工持续 3 秒 → 自动重新初始化 PHY 重新协商（最多 3 次，
            间隔 8 秒），争取回到 100M 全双工；不用改通告能力，避免协商不上 */
#define FW_VERSION_STR   "ver 2.1"

#endif
