# AI 决策服务上线运维说明

本文档记录 2026-11-06 的上线配置，**下次重启机器或换网络时照着做即可**。

## 线上拓扑

```
浏览器（任意设备）
   │  https://platform.zhka.qianxiao.xin/brain/...
   ▼
Nginx（81.70.63.53:443）
   │  反代 /brain/ → 127.0.0.1:5001
   ▼
frps（服务器，127.0.0.1:5001 监听）
   │  ← 隧道（frpc 主动向外连接 7000）
   ▼
frpc（操作者本机）
   │  → 127.0.0.1:5001
   ▼
Python 决策服务（本机 5001）→ MQTT 1883 → 固件
```

**为什么必须用隧道**：页面是 HTTPS，Python 是 HTTP。浏览器会按混合内容拦截
https 页面发起的 http 请求，这是规范强制的，业务代码绕不过。隧道把 Python
"搬"到服务器回环，让 nginx 以同源方式反代，问题自然消失。

同时服务器在公网，也访问不到操作者的内网 IP（`192.168.x.x`），必须由本机主动外连。

## 服务器侧（已配置好，一般不用动）

| 项 | 值 |
|---|---|
| frps 二进制 | `/opt/frp/frps`（v0.61.1） |
| frps 配置 | `/opt/frp/conf/frps.toml` |
| 服务 | `systemctl status frps`（已设开机自启） |
| 监听 | `0.0.0.0:7000`（控制）、`127.0.0.1:7500`（面板） |
| 令牌 | `zhka-brain-2026` |
| 端口白名单 | 只允许映射 5001，避免机器被当跳板 |

nginx 规则在 `/www/server/panel/vhost/nginx/platform.zhka.qianxiao.xin.conf`：

```nginx
location ^~ /brain/ {
    proxy_pass http://127.0.0.1:5001/;
    ...
}
```

> **`proxy_pass` 末尾的斜杠不能少**：它让 `/brain/api/brain/status` 剥掉 `/brain/`
> 前缀后变成 `/api/brain/status`，正好对上 Python 的路由。
> 少了斜杠会变成 `/brain/api/brain/status`，直接 404。

> **改完 nginx 必须 `systemctl restart nginx`，不能用 reload**。
> 这台机器 reload 后 worker 仍按旧配置转发（`nginx -T` 显示新配置但实际不生效）。
> 验证方法：`ps -eo pid,lstart,cmd | grep 'nginx: master'` 看 master 启动时间是否变化。

## 本机侧（每次开机要做）

### 1. 启动 Python 服务

```powershell
cd E:\Users\CKJ\Desktop\Zhihukuan\Software\reservoir-platform\inference
$env:MQTT_ENABLED="true"
$env:MQTT_BROKER="tcp://127.0.0.1:1883"
$env:AUTO_DECIDE="true"
$env:DISPATCH_CONTROL="true"    # 真实下发闸门指令；只想观察就设 false
$env:GATE_COUNT="4"
$env:STATION_NAME="智护库安演示站"
python -m uvicorn server:app --host 0.0.0.0 --port 5001
```

现场无硬件时，另开一个终端跑模拟数据源：

```powershell
cd E:\Users\CKJ\Desktop\Zhihukuan\Software\reservoir-platform\inference
python tools/demo_feed.py --port 1883 --interval 1.5 --start-level 1.15
```

### 2. 启动隧道

双击 `C:\Users\CKJ\zhka-frpc\frp_0.61.1_windows_amd64\启动隧道.bat`

看到 `start proxy success` 即成功。

### 3. 验证

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://platform.zhka.qianxiao.xin/brain/health
# 期望 200
```

浏览器打开 `https://platform.zhka.qianxiao.xin/#/flood`，水位和闸门应实时刷新。

## 配置文件的坑（已经踩过）

`frpc.toml` 的 TOML 表顺序很关键：**一旦写了 `[transport]`，后面所有键都归它管**。

```toml
# ✅ 正确：顶层键在前
log.to = "frpc.log"
log.level = "info"

[transport]
heartbeatInterval = 10

[[proxies]]
name = "brain-5001"
...

# ❌ 错误：log 写到 [transport] 之后就变成 transport.log，frpc 报
#    json: unknown field "log"
```

同理 `heartbeatInterval` 属于 `[transport]` 表，**不能**写在 `[[proxies]]` 里，
否则报 `unmarshal ProxyConfig error: json: unknown field "heartbeatInterval"`。

改完先校验，别直接启动：

```powershell
cd C:\Users\CKJ\zhka-frpc\frp_0.61.1_windows_amd64
.\frpc.exe verify -c frpc.toml
```

## 安全组

阿里云安全组需放行 `TCP 7000`（入方向）。2026-11-06 已放行。
若换服务器需要重新配置。

## 回滚

前端旧版本保留在服务器：

```bash
ls -d /www/wwwroot/zhka/h5/reservoir-platform.old-*
```

回滚（先停站点再换目录，避免出现半旧半新）：

```bash
cd /www/wwwroot/zhka/h5
mv reservoir-platform reservoir-platform.new-$(date +%Y%m%d-%H%M%S)
mv reservoir-platform.old-20261106-102736 reservoir-platform
chown -R www:www reservoir-platform
```

整站备份：`/root/zhka-frontend-backup-20261106-102310.tar.gz`

## 待办：总线客户端尚未配置

全局开闸确认弹窗依赖服务接入总线推送 `brain.approval_request` 事件。
目前 `BUS_CLIENT_ID` / `BUS_CLIENT_SECRET` 为空，所以**弹窗不会自动出现**
（决策照常运行，只是待确认请求推不到前端）。

启用步骤：

1. 管理员登录平台 →「管理中心 → 服务接入」→ 新建客户端
   - `client_id`：`dam-brain`
   - `allow_publish`：`brain.#`
   - `allow_subscribe`：`none`
2. 保存返回的 secret（只显示一次）
3. 启动 Python 服务时加上：

```powershell
$env:BUS_BASE_URL="http://81.70.63.53:8085"
$env:BUS_CLIENT_ID="dam-brain"
$env:BUS_CLIENT_SECRET="<创建时返回的密钥>"
```

## 已知局限

1. **多闸门预测是线性近似**。模型只在单门 0/1 上训练（683 条样本全是单门），
   4 门并用时按「单门基准 × N」缩放。总流量受来水限制，4 门全开的误差会放大。
   要更准需要按「N 门同时开」重新采集数据训练。

2. **排水速率快时可能振荡**。若 4 门全开 7.5 秒（一个保持期）就把水位砸回正常区，
   AI 会立刻关闸，水位再涨回去形成「开-关-开」。需要按现场实际排水速率
   调 `CostWeights.rapid_change_threshold` 和 `hold_steps`。

3. **MQTT broker 在本机**。`demo_feed.py` 只用于演示；接真实硬件时把
   `MQTT_BROKER` 指向现场 broker，并关掉 demo_feed。

4. **隧道依赖本机开机**。本机睡眠或断网，线上页面会显示「AI 服务离线」
   （闸门手动控制不受影响，因为那是前端直连 MQTT）。
