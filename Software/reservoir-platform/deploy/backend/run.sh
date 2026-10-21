#!/usr/bin/env bash
# 后台服务的简易启动脚本（不用 systemd 时使用）
#
#   nohup ./run.sh > /dev/null 2>&1 &
#
# 关键点：先 cd 到脚本所在目录，让 .env 落在"当前工作目录"，
# 这样 application.yml 里的 optional:file:.env[.properties] 才能读到它。
set -euo pipefail

cd "$(dirname "$0")"

JAR="${JAR:-dam-server-2.0.1.jar}"
JAVA_OPTS="${JAVA_OPTS:--Xms256m -Xmx512m}"

# 想摆脱工作目录依赖，就改用绝对路径（注意方括号要整体加引号，
# 否则 bash 会把它当通配符）：
#   EXTRA=(--spring.config.import='optional:file:/www/wwwroot/zhka/backend/.env[.properties]')
EXTRA=()

exec java $JAVA_OPTS -jar "$JAR" --server.address=127.0.0.1 "${EXTRA[@]}" "$@"
