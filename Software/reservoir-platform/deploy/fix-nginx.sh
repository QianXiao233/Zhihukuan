#!/usr/bin/env bash
# =============================================================================
# 一键修复 zhka.demo.ai.qianxiao.xin 的「前端 502 / 接口不通」
#
#   1. 备份当前 vhost 和 proxy 相关文件
#   2. 把 81.70.63.53:8000 全部改成 127.0.0.1:8085
#   3. 修掉 try_files 里的绝对路径（会把 root 拼两遍）
#   4. 自动定位真正有 index.html 的目录并写回 root
#   5. 缺 /auth/ 反代就补上
#   6. nginx -t 通过才 reload，失败自动回滚
#   7. 后端没起就拉起来，最后跑三项验证
#
# 用法：
#   bash fix-nginx.sh
#
# 幂等：重复执行不会产生重复配置（每步都有存在性判断）。
# =============================================================================
set -uo pipefail

DOMAIN="zhka.demo.ai.qianxiao.xin"
VHOST_DIR="/www/server/panel/vhost/nginx"
VHOST="$VHOST_DIR/html_$DOMAIN.conf"
BACKEND="127.0.0.1:8085"
BACKUP_DIR="/root/vhost-backup-$(date +%F-%H%M%S)"
LOG="/www/wwwlogs/reservoir-backend.log"

info()  { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
warn()  { printf '\033[33m[!]\033[0m %s\n' "$*"; }
err()   { printf '\033[31m[X]\033[0m %s\n' "$*"; }

# ── 0. 前置检查 ───────────────────────────────────────────────────────────────
if [ ! -f "$VHOST" ]; then
    err "找不到 $VHOST"
    echo "现有 vhost："; ls -l "$VHOST_DIR" | grep -i zhka
    exit 1
fi
mkdir -p "$BACKUP_DIR"
cp -a "$VHOST" "$BACKUP_DIR/" 2>/dev/null
info "已备份到 $BACKUP_DIR"

# ── 1. 移走其它同样声明本域名的 vhost（重复 server_name 会让旧块生效）──────
for f in "$VHOST_DIR"/*.conf; do
    [ "$f" = "$VHOST" ] && continue
    if grep -q "server_name[[:space:]]\+$DOMAIN" "$f" 2>/dev/null; then
        mv "$f" "$BACKUP_DIR/"
        warn "移走重复声明 $DOMAIN 的 vhost：$f"
    fi
done

# ── 2. 指向后端 ───────────────────────────────────────────────────────────────
sed -i 's#81\.70\.63\.53:8000#127.0.0.1:8085#g' "$VHOST"
sed -i 's#http://reservoir_backend#http://127.0.0.1:8085#g' "$VHOST"
info "上游已改为 http://$BACKEND"

# ── 3. try_files 不能写绝对路径，否则 root 会被拼两遍 ────────────────────────
sed -i 's#try_files \$uri \$uri/ /[^;]*index\.html;#try_files \$uri \$uri/ /index.html;#' "$VHOST"

# ── 4. 定位真实前端目录 ───────────────────────────────────────────────────────
ROOT=""
for d in /www/wwwroot/zhka/reservoir-platform \
         "/www/wwwroot/$DOMAIN" \
         /www/wwwroot/zhka/h5/ai-vue; do
    if [ -f "$d/index.html" ]; then ROOT="$d"; break; fi
done
if [ -z "$ROOT" ]; then
    ROOT=$(find /www/wwwroot -maxdepth 4 -name index.html -printf '%h\n' 2>/dev/null \
           | grep -v node_modules | head -1)
fi
if [ -n "$ROOT" ]; then
    sed -i "0,/^[[:space:]]*root[[:space:]]/s#^[[:space:]]*root[[:space:]].*#    root $ROOT;#" "$VHOST"
    info "root = $ROOT"
else
    warn "没找到任何 index.html，root 未修改，请手动确认："
    grep -n 'root ' "$VHOST" | head -5
fi

# ── 5. 补 /auth/ 反代（老模板没有，登录会 404）──────────────────────────────
if ! grep -q 'location .*/auth/' "$VHOST"; then
    awk -v be="$BACKEND" '
        /^[[:space:]]*server_name[[:space:]]/ && !done {
            print; print "";
            print "    # 登录 / 注册 / 令牌校验";
            print "    location ^~ /auth/ {";
            print "        proxy_pass http://" be ";";
            print "        proxy_buffering off;";
            print "    }";
            done = 1; next
        }
        { print }
    ' "$VHOST" > "$VHOST.tmp" && mv "$VHOST.tmp" "$VHOST"
    info "已补上 /auth/ 反代"
else
    info "/auth/ 反代已存在"
fi

# ── 6. SSE：/api/ 里补 proxy_buffering off（没有的话流式回答会被攒住）───────
if grep -q 'location .*/api/' "$VHOST" && ! grep -q 'proxy_buffering off' "$VHOST"; then
    sed -i '/location .*\/api\//,/^[[:space:]]*}/ s#^\([[:space:]]*proxy_pass[^;]*;\)#\1\n        proxy_buffering off;\n        proxy_read_timeout 3600s;#' "$VHOST"
    info "已为 /api/ 关闭缓冲"
fi

# ── 7. 语法检查 + 重载，失败自动回滚 ──────────────────────────────────────────
if nginx -t 2>/tmp/nginx-t.err; then
    nginx -s reload
    info "nginx 已重载"
else
    err "nginx -t 失败："; cat /tmp/nginx-t.err
    cp -a "$BACKUP_DIR"/*.conf "$VHOST_DIR"/ 2>/dev/null
    warn "已回滚到 $BACKUP_DIR"
    exit 1
fi

# ── 8. 后端没起来就拉起来 ─────────────────────────────────────────────────────
if ! curl -s -m 2 -o /dev/null "http://$BACKEND/health"; then
    JAR=$(find /www/wwwroot/zhka -maxdepth 4 -name 'dam-server-*.jar' 2>/dev/null | head -1)
    if [ -n "$JAR" ]; then
        warn "后端未监听，启动 $JAR"
        ( cd "$(dirname "$JAR")" && nohup java -jar "$JAR" --server.address=127.0.0.1 >> "$LOG" 2>&1 & )
        for _ in $(seq 1 20); do
            sleep 1
            curl -s -m 2 -o /dev/null "http://$BACKEND/health" && break
        done
    else
        err "没找到 dam-server-*.jar，请手动启动后端"
    fi
fi

# ── 9. 验证 ───────────────────────────────────────────────────────────────────
echo
echo "──────── 验证 ────────"
printf '后端直连    : '; curl -s -o /dev/null -w '%{http_code}\n' "http://$BACKEND/health"
printf 'nginx/health: '; curl -sk --resolve "$DOMAIN:443:127.0.0.1" -o /dev/null -w '%{http_code}\n' "https://$DOMAIN/health"
printf 'nginx/api   : '; curl -sk --resolve "$DOMAIN:443:127.0.0.1" -o /dev/null -w '%{http_code}\n' "https://$DOMAIN/api/get_rsa"
echo
echo "旧地址残留计数（应为 0）："
nginx -T 2>/dev/null | grep -c '81.70.63.53:8000'
echo "8085 出现次数（应 ≥1）："
nginx -T 2>/dev/null | grep -c '127.0.0.1:8085'
echo
if curl -sk --resolve "$DOMAIN:443:127.0.0.1" "https://$DOMAIN/api/get_rsa" | head -1 | grep -q 'BEGIN PUBLIC KEY'; then
    info "全部通过，去浏览器刷新登录页（Ctrl+F5 清缓存）"
else
    warn "还有问题，看这个："
    tail -3 "/www/wwwlogs/$DOMAIN.error.log"
fi
