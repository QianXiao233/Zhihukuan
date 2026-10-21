# 前端构建与 Nginx 部署

前端是 Vue3 + Vite，后端是 Spring Boot（`127.0.0.1:8085`）。部署后两者**同源**，
前端只用相对路径 `/api`、`/auth`、`/health`，由 Nginx 反代到后端，因此不存在跨域问题。

- Nginx 配置：[`deploy/nginx/zhka.demo.ai.qianxiao.xin.conf`](nginx/zhka.demo.ai.qianxiao.xin.conf)
- 站点根目录：`/www/wwwroot/zhka/reservoir-platform`（配置里的 `root`，按需修改）

---

## 1. 本地构建

```bash
cd frontend
npm ci            # 没有 lock 文件时用 npm install
npm run build     # 产物在 frontend/dist
```

> 不要设置 `VITE_API_BASE`。留空才会走同源相对路径，交给 Nginx 转发。
> 站点走 HTTPS 时，MQTT 必须用 `wss://`（浏览器会拦 `ws://` 混合内容），构建前加：
>
> ```bash
> VITE_MQTT_BROKER_URL=wss://zhka.demo.ai.qianxiao.xin/mqtt npm run build
> ```
>
> 对应 nginx 里的 `location ^~ /mqtt`（已默认启用），详见第 7 节。
> 若忘了加这个变量，产包里会留下 `ws://81.70.63.53:8083/mqtt`，实时监测页会一直是未连接。

构建产物结构（Vite 默认）：

```
dist/
├── index.html
└── assets/   # 文件名带 content hash，可长缓存
```

## 2. 上传到服务器

```bash
# 本地执行（把 dist 内容整体传到站点根目录，注意是 dist 里的内容，别多套一层 dist）
scp -r frontend/dist/* root@<服务器IP>:/www/wwwroot/zhka/reservoir-platform/

# 服务器上修正属主/权限（宝塔面板默认 www 用户）
chown -R www:www /www/wwwroot/zhka/reservoir-platform
chmod -R 755 /www/wwwroot/zhka/reservoir-platform
```

目录里最终应该是 `/www/wwwroot/zhka/reservoir-platform/index.html` 和 `assets/`。

## 3. 启用 Nginx 配置

把 `deploy/nginx/zhka.demo.ai.qianxiao.xin.conf` 放到宝塔的 vhost 目录：

```bash
nginx -t && systemctl restart nginx
```

> **这台机器上 `nginx -s reload` 不生效**——`nginx -T` 读的是磁盘文件，会显示新配置，
> 但运行中的 worker 仍按旧配置转发（表现为「文件改了、reload 也成功了，接口还是 502」）。
> 改完配置一律用 `systemctl restart nginx`（或宝塔面板里的「重启」），
> 并用 `ps -eo pid,lstart,cmd | grep 'nginx: master'` 确认 master 的启动时间变了。

宝塔面板里的位置是 `/www/server/panel/vhost/nginx/zhka.demo.ai.qianxiao.xin.conf`，
在「网站 → 设置 → 配置文件」里**整体替换，不要往已有内容里粘贴**。

> 这个文件本身就是一个完整的 `server { }`，粘贴到面板已有的 vhost 里会出现
> `nginx: [emerg] duplicate location "/"`（面板默认已经带了 `location /`）。
> 本配置因此**刻意不写** `location /`：hash 路由不需要 `try_files`，静态文件由
> nginx 隐式 location + `index` 指令提供，功能不受影响。
> 若已经粘出重复，删掉多出来的那个 `location / { ... }` 即可。

配置与模板保持一致，保留了：

- `CERT-APPLY-CHECK` 与 `extension`、`well-known`、`rewrite` 三处 include；
- HTTP 跳 HTTPS、QUIC/HTTP3、SSL 套件、HSTS、Alt-Svc；
- 敏感文件/目录 404、证书目录校验、静态资源 expires。

**要按实际情况改的三处**：`server_name`、`root`、证书路径（面板申请证书后一般不用动）。

## 4. 后端前置条件

Nginx 只做转发，502 基本都是后端没起或端口不对。逐项确认：

```bash
# 后端必须在本机 8085 上监听（application.yml: server.port=8085）
ss -lntp | grep 8085
curl -i http://127.0.0.1:8085/health
```

`/health` 正常返回形如：

```json
{"status":"ok","dify_api_base":"https://dify.qianxiao.xin/v1","dify_key_configured":true,"asr_available":false,"tts_provider":"browser"}
```

后端需要的环境变量（`backend/.env`，模板见 `.env.example`）：

| 变量 | 说明 |
| --- | --- |
| `DIFY_API_KEY` | 必填，否则问答接口报未配置 |
| `JWT_SECRET` | 生产务必固定，否则重启后所有人要重新登录 |
| `DB_URL` / `DB_USERNAME` / `DB_PASSWORD` | 登录、台账、阈值、消息、推送配置依赖 MySQL |
| `MONGO_URI` | **必填（否则水情数据无处可存）**，形如 `mongodb://zhka-db:密码@81.70.63.53:27017/zhka-db?authSource=zhka-db`；**路径里必须带库名**，`authSource` 指向存放该账号的库 |
| `MQTT_BROKER` | 后端订阅 `rtu/status` 用，如 `tcp://81.70.63.53:1883` |
| `ALERT_ENABLED` / `ALERT_COOLDOWN_MINUTES` | 是否启用阈值告警、同一指标的推送冷却分钟数（默认 10） |
| `PUSH_TOKEN` | 可选的兜底 token；正式 token 在管理页维护，一般留空 |
| `app.cors.allowed-origin-patterns` | 前端域名白名单，**同域部署也必须写**，否则登录被 403 `Invalid CORS request` 挡住 |

> **broker 与后端同机时，不要用公网 IP。** 云主机的公网 IP 是 NAT 映射，并不在网卡上，
> 服务器访问自己的 EIP 需要 NAT 回流（hairpin），多数云默认不支持；如果 broker 还在 Docker 里，
> 宿主经公网 IP / 内网 IP 访问也不通——docker 的 DNAT 规则只在 `PREROUTING` 生效，
> 而本机发出的流量走 `OUTPUT`，压根不经过它。服务器上改成本机回环即可：
>
> ```dotenv
> MQTT_BROKER=tcp://127.0.0.1:1883
> ```
>
> 本地开发仍填 `tcp://81.70.63.53:1883`，**两份 `.env` 本来就该不同**，
> 别把本地那份直接 `scp` 上去覆盖。改完重启后端，日志里应出现
> `[MQTT] 已连接 tcp://127.0.0.1:1883，订阅主题: rtu/status`。
>
> 确认容器端口发布情况：
>
> ```bash
> docker ps --format '{{.Names}}\t{{.Ports}}' | grep -i emqx
> docker port <容器名>                  # 期望 1883/tcp -> 0.0.0.0:1883
> nc -vz 127.0.0.1 1883                 # 期望 succeeded
> ```
>
> 如果 `docker port` 显示的是 `某个内网IP:1883` 而不是 `0.0.0.0:1883`，
> 就把 `MQTT_BROKER` 换成那个 IP（`127.0.0.1` 上没有监听）。
> 若容器没有发布端口、只在自定义 bridge 网络里可达，
> 用 `docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <容器名>` 取容器 IP。

后端进程建议只监听回环地址，外网一律经 Nginx：

```bash
# 启动示例（按实际 jar 名/路径调整）
nohup java -jar /www/wwwroot/zhka/reservoir-platform/backend.jar \
  --server.address=127.0.0.1 > /www/wwwlogs/reservoir-backend.log 2>&1 &
```

> 后端 `application.yml` 里的 `server.address` 目前是 `0.0.0.0`，等于 8085 直接暴露公网。
> 只想经 Nginx 访问的话，用启动参数覆盖成 `127.0.0.1` 更安全。

## 5. 验证清单

```bash
# ① 静态页
curl -I https://zhka.demo.ai.qianxiao.xin/
curl -I https://zhka.demo.ai.qianxiao.xin/assets/        # 应 404，但不该 403

# ② 健康检查（走反代）
curl -s https://zhka.demo.ai.qianxiao.xin/health

# ③ 登录页用到的公钥接口（返回纯文本 RSA 公钥）
curl -s https://zhka.demo.ai.qianxiao.xin/api/get_rsa | head -2

# ④ SSE 流式对话：关键看是否"逐条"输出，而不是憋到最后一次性吐出
curl -N -X POST https://zhka.demo.ai.qianxiao.xin/api/chat/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"你好","conversation_id":"","file_ids":[]}'

# ⑤ 文件上传（10MB 以内；超过 40MB 会 413）
curl -i -F "file=@./test.png" https://zhka.demo.ai.qianxiao.xin/api/files/upload
```

浏览器端再看一眼 DevTools → Network：`/api/chat/stream` 的响应类型应为
`text/event-stream`，且是 `EventStream` 分块到达。

## 6. 已覆盖的接口

配置里的三条反代，对应 `frontend/vite.config.js` 里的三个 proxy：

| 前端调用 | 用途 | Nginx 位置 |
| --- | --- | --- |
| `/api/chat/stream`、`/api/chat` | 流式/阻塞问答 | `location ^~ /api/` |
| `/api/files/upload`、`/api/asr` | 多模态文件、语音识别 | 同上 |
| `/api/get_rsa` | 登录前取 RSA 公钥 | 同上 |
| `/api/manage/**` | 坝体/设备/参数/用户/审计/数据 | 同上 |
| `/api/get_messagelist`、`/api/mark_message_read` 等 | 消息中心 | 同上 |
| `/auth/login`、`/auth/register`、`/auth/validate` | 登录鉴权 | `location ^~ /auth/` |
| `/health` | 健康检查 | `location = /health` |

关键点：

- `/api/` 关掉了 `proxy_buffering`，否则 SSE 会被缓存；`proxy_read_timeout` 提到 3600s。
- `client_max_body_size 40m` 与后端 multipart 上限对齐，否则上传直接 413。
- `X-Forwarded-*` 三个头齐全，后端 `forward-headers-strategy: framework` 能还原真实来源 IP 和协议。
- 路由是 hash 模式（`createWebHashHistory`），刷新子页面不需要 rewrite；`location /` 的
  `try_files` 只是给将来改 history 模式留的兜底。

## 7. 两个不在 8085 上的外部服务

这两个**不要**反代到 Java 后端，它们不是同一个进程：

1. **MQTT Broker**（EMQX，宿主机 `8083` 是 WebSocket 监听）
   页面走 HTTPS 时浏览器会拦 `ws://`（混合内容），所以统一走 nginx 反代：
   `wss://域名/mqtt` → `location ^~ /mqtt` → `http://127.0.0.1:8083/mqtt`。
   构建时必须带 `VITE_MQTT_BROKER_URL=wss://zhka.demo.ai.qianxiao.xin/mqtt`，
   否则产物里会留下 `ws://81.70.63.53:8083/mqtt`，实时监测页一直未连接。
   验证：`curl -i --http1.1 -H 'Upgrade: websocket' -H 'Connection: Upgrade' ...` 应返回 `101`。

2. **无人艇串口桥**（`boatControlService.js` 固定 `http://127.0.0.1:4174`）
   这是**操作者本机**的 serial-service，不是服务器上的服务，必须保持 `127.0.0.1`，
   反代到服务器反而会让 BoatView 页面彻底不可用。

3. Janus 视频网关（`BoatView.vue` 里 `http://192.168.2.14:8088/janus`）属于局域网设备，
   同样不经过本站 Nginx。

## 8. 常见报错速查

| 现象 | 原因 |
| --- | --- |
| 502 Bad Gateway | 后端没起 / 端口不是 8085 / 只监听了别的地址 |
| 413 Request Entity Too Large | `client_max_body_size` 小于文件；本配置已放到 40m |
| 上传成功但问答报错 | 后端到 Dify 的 `DIFY_API_KEY` 未配置 |
| 回答"憋一大段才出来" | `/api/` 的 `proxy_buffering off` 没生效，或有别的 `add_header`/gzip 层干扰 |
| 刷新页面 404 | 用了 history 路由但缺 `try_files`；本配置已兜底 |
| 登录一直跳回登录页 | `JWT_SECRET` 每次重启都变，或后端时钟偏差 |
| 登录点下去 403，响应体只有 `Invalid CORS request`（20 字节） | `.env` 缺 `app.cors.allowed-origin-patterns`；浏览器 POST 必带 `Origin`，而 curl 不带，所以用 curl 测不出来 |
| `nginx -t` 报 `unknown directive "quic"` | 当前 nginx 不支持 QUIC（需宝塔/Tengine 的 quic 版本），先删掉 `listen 443 quic; http3 on; quic_retry/quic_gso` |

---

## 9. 后端 jar 的 `.env` 放哪

**结论：放在启动 jar 时的工作目录里**，不是 jar 内部，也不是"jar 同目录"（除非你正好 cd 到那）。

原因在 `application.yml` 第 11 行：

```yaml
spring.config.import: optional:file:.env[.properties]
```

- `file:.env` 是**相对路径**，按进程工作目录（cwd）解析，跟 jar 在哪个目录无关；
- `.env` 只存在于 `backend/.env`，不在 `src/main/resources`，所以 `mvn package` 不会把它打进 jar，**必须单独上传**；
- `[.properties]` 是扩展名提示，必须有——`.env` 不是 Spring 认识的后缀，去掉提示会静默不加载；
- `optional:` 表示文件不存在也照常启动，但 `DIFY_API_KEY` 为空，`/health` 返回 `dify_key_configured:false`，问答接口报错。**"能启动"≠"配置生效"**。

### 推荐的服务器布局

```
/www/wwwroot/zhka/backend/          # 不在 nginx root 内，避免被静态服务读到
├── dam-server-2.0.1.jar
├── .env                            # chown www:www && chmod 600
└── run.sh
```

前端静态文件在 `/www/wwwroot/zhka/reservoir-platform`，后端 jar 和 `.env` 放到它**外面**的 `backend/` 目录。虽然 nginx 配置里 `.env.*` 已经 `return 404`，但没必要赌这一层。

### 三种落地方式（选一）

| 方式 | 做法 | 适用 |
| --- | --- | --- |
| ① cd 到目录 | `cd /www/wwwroot/zhka/backend && java -jar dam-server-2.0.1.jar` | 最省事，yml 不用改 |
| ② 显式绝对路径 | `java -jar x.jar '--spring.config.import=optional:file:/www/wwwroot/zhka/backend/.env[.properties]'` | 没法控制 cwd 时 |
| ③ systemd | `WorkingDirectory=` + `EnvironmentFile=`，见 [`backend/reservoir-backend.service`](backend/reservoir-backend.service) | 生产推荐 |

方式 ② 的方括号**必须用引号包住**，否则 bash 会把它当字符集通配符（`[.properties]` 匹配 `.`/`p`/`r`... 中的单个字符）。

方式 ③ 里 `EnvironmentFile` 就是 systemd 直接读 `.env` 当环境变量，此时连 `spring.config.import` 都不需要参与。

### 优先级（高 → 低）

```
命令行参数  --key=value
系统环境变量 / systemd Environment=
.env                     (spring.config.import 导入的文档)
application.yml          内置默认值
```

所以临时排查可以直接 `java -jar x.jar --reservoir.dify.api-key=app-xxx` 覆盖，不用改文件。

### `.env` 的格式陷阱

它是被当 **properties** 解析的，不是 shell：

- ❌ 不要写 `export DIFY_API_KEY=xxx`（key 会变成 `export DIFY_API_KEY`）
- ❌ 不要给值加引号（`DB_PASSWORD="123456"` 会把引号带进密码）
- ✅ `#` 注释、空行可以
- ✅ 空值合法：`DB_PASSWORD=`
- ✅ 值里的 `&`（`DB_URL` 的查询参数）不用转义

### 验证配置真的读到了

```bash
curl -s http://127.0.0.1:8085/health
# {"status":"ok", ..., "dify_key_configured":true, ...}   ← 这里必须是 true
```

---

## 10. 水情数据迁移到 MongoDB

本次改造把**水情读数**从 MySQL 的 `water_log` 搬到了 MongoDB，MySQL 继续承载登录、台账、
阈值、消息、告警记录与推送配置。两部分是独立连接：MongoDB 没启动不影响应用启动，也不影响问答。

**MongoDB 只存水情读数**，其余全部在 MySQL：

| 数据 | 存储 |
| --- | --- |
| 水情读数（水位 / 液温 / pH / ORP / 6 路闸门） | MongoDB `water_readings` |
| 登录用户、坝体、设备、阈值、消息、审计、告警记录、推送配置 | MySQL（`user` / `dam_info` / `dam_device` / `dam_system_param` / `message` / `platform_audit` / `alert_event` / `platform_setting`） |

### 10.1 集合与索引

| 集合 | 内容 | 索引 |
| --- | --- | --- |
| `water_readings` | 水情读数 | `time`（降序）、`legacyId`（唯一稀疏，迁移幂等用） |

索引在**首次写入**时自动创建（`WaterReadingQueryRepository#ensureIndexes`），
不需要手工建；也可以按 `backend/db/mongodb-init.js` 手动初始化。

### 10.2 服务器上准备 MongoDB

```bash
# 以 Ubuntu 22.04 为例（其它发行版见 MongoDB 官方文档）
sudo apt-get install -y mongodb-org || true   # 若未配置官方源，按官方文档添加后再装
sudo systemctl enable --now mongod
mongosh --quiet --eval 'db.runCommand({ping:1})'   # { ok: 1 }
```

后端只要改 `.env`：

```dotenv
# 本项目当前连的是 81.70.63.53 上的 zhka-db 库
MONGO_URI=mongodb://zhka-db:密码@81.70.63.53:27017/zhka-db?authSource=zhka-db&connectTimeoutMS=3000&serverSelectionTimeoutMS=3000
```

> - **URI 路径里的库名不能省**（这里是 `/zhka-db`）：只写 `mongodb://host:27017/?authSource=...`
>   时 Spring Data 找不到默认库，启动会报 `Database name must not be empty`。
> - `authSource` 是存放该账号的库，通常与库名相同；账号建在 `admin` 库则写 `authSource=admin`。
> - MongoDB 与后端同机时把 host 换成 `127.0.0.1`；URL 里的 `&` 在 `.env` 里**不用**转义。

### 10.3 迁移历史数据（可重复执行）

旧表 `water_log` 不会被删除，迁移接口按 `id` 游标分批读取，并用 `legacyId` 去重：

```bash
# 管理页「数据维护 → 迁移历史数据」按钮，等价于：
TOKEN=<登录后的 JWT>
curl -s -X POST http://127.0.0.1:8085/api/manage/data/migrate \
  -H "Authorization: Bearer $TOKEN"
# {"success":true,"data":{"read":12345,"inserted":12345,"skipped":0,"elapsedMs":820}}
```

迁移完成、抽查无误后，`water_log` 可以自行 `DROP TABLE`（脚本不会删）。

### 10.4 推送 token 与冷却时间

以前 token 硬编码在 `AuthController` 里，现在改到 **系统设置 → 推送与告警**：

- token 存 MySQL 的 `platform_setting.push.token`，页面只回显掩码（前 6 + 后 4）；
- 冷却时间存 `push.cooldown_minutes`，同一指标在窗口内只推一次；
- 登录异常告警按**账号**独立冷却（`LOGIN_ALERT_COOLDOWN_MINUTES`，默认 5 分钟）；
- 「发送测试消息」绕过冷却，用来验证 token；
- 旧环境执行一次 `backend/db/management-upgrade.sql` 建表并写入默认值
  （默认 token 是从旧代码迁移过来的，**建议在页面上更换**）。

### 10.5 告警链路

```
MQTT 上报 → MqttService 解析 → ThresholdMonitorService 比对 dam_system_param 的上下限
        → 越界？→ PushCooldownService 是否在冷却期？→ 否 → PushService 异步推送
        → 结果写入 MySQL 的 alert_event（成功/失败/未配置 token 都记录）
```

- 实时监测页顶部会显示后端检出的越界项与推送状态；
- 冷却期内被抑制的次数会累加显示，只有真正触发的告警才落库，不会把 `alert_event` 写爆；
- 阈值在参数页修改后立即生效（`ThresholdProvider` 有 20 秒缓存，保存时会主动失效）。

### 10.6 数据维护页能力

- 按时间范围、四个指标的数值区间、6 路闸门状态、是否越界组合筛选；
- 统计卡片 + 按小时/按天分桶的水位趋势 + 指标 min/avg/max + 闸门开启率；
- 按当前筛选导出 CSV（上限 10000 条）、按时间清理历史数据；
- 存储状态条显示 MongoDB 是否连上、文档数、旧 MySQL 表剩余条数。

### 10.7 落库频率

水情记录默认**每 10 秒**写一条（取该窗口内收到的最新一帧），由
`MQTT_SAVE_INTERVAL_SECONDS` 控制：

```dotenv
MQTT_SAVE_INTERVAL_SECONDS=10
```

- 旧变量 `MQTT_SAVE_INTERVAL`（分钟）已废弃，升级后请改名；
- 只有收到过新数据才会写，MQTT 断线期间不会产生空记录；
- 10 秒一条约 8640 条/天，MongoDB 单机完全够用；需要更细的可调到 5 秒或 1 秒。



启动日志里也能看到导入的配置源，确认 `.env` 的绝对路径符合预期。
