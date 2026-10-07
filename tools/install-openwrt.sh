#!/bin/sh
# OpenWrt / Alpine 等 musl 路由器一键安装系统级保活
# 用法: 下载 zju-autologin-linux-musl 后执行:
#   ./install-openwrt.sh ./zju-autologin-linux-musl 学号 [-- 密码]
# 密码缺省时交互输入; 也可 PASS=密码 环境变量。
set -e

BIN="${1:?用法: $0 <zju-autologin-linux-musl 路径> <学号> [-- 密码]}"
USER_ID="${2:?缺少学号}"
shift 2 || true
if [ "$1" = "--" ]; then
  PASS="$2"
  shift 2
fi
[ -n "$PASS" ] || PASS="$PASS_ENV"
# 摘要: `[ -n "$PASS" ] || [ -t 0 ] && { ...read... }` 会被解析成
# ([ -n "$PASS" ] || [ -t 0 ]) && {...} —— 已经给了密码也会去读, 把 PASS 清空,
# 于是"命令行给了密码"反而必然失败。必须写成显式 if。
if [ -z "$PASS" ] && [ -t 0 ]; then
  printf '校园网密码: '; stty -echo; read PASS; stty echo; printf '\n'
fi
[ -n "$PASS" ] || { echo "未提供密码"; exit 1; }

[ "$(id -u)" = 0 ] || { echo "需要 root: 请用 sudo/opkg 终端执行"; exit 1; }
[ -x "$BIN" ] || chmod +x "$BIN"

BIN_ABS="$(cd "$(dirname "$BIN")" && pwd)/$(basename "$BIN")"
install -m 0755 "$BIN_ABS" /usr/bin/zju-autologin

# procd 服务(OpenWrt) 或 systemd(Alpine)
if command -v uci >/dev/null 2>&1; then
  cat > /etc/init.d/zju-autologin <<'EOF'
#!/bin/sh /etc/rc.common
START=99
USE_PROCD=1
start_service() {
    procd_open_instance
    procd_set_param command /usr/bin/zju-autologin watch --config /etc/zju-autologin/config.json
    procd_set_param respawn 3600 5 0
    procd_set_param stdout 1
    procd_set_param stderr 1
    procd_close_instance
}
EOF
  chmod +x /etc/init.d/zju-autologin
  INIT_OK=1
else
  cat > /etc/systemd/system/zju-autologin.service <<'EOF'
[Unit]
Description=ZJU Campus Network AutoLogin (srun keepalive)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/bin/zju-autologin watch --config /etc/zju-autologin/config.json
Restart=always
RestartSec=15
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  INIT_OK=1
fi

mkdir -p /etc/zju-autologin
printf '%s' "$PASS" | "$BIN_ABS" enable -u "$USER_ID" --pass-stdin || {
  # enable 走 systemd; procd 环境手动写最小配置
  cat > /etc/zju-autologin/config.json <<EOF2
{"password_backend":"file","username":"$USER_ID","domain":"","interval":60,
 "auto_login":true,"base_url":"https://net.zju.edu.cn","ac_id":"80",
 "password_b64":"$(printf '%s' "$PASS" | base64 | tr -d '\n')"}
EOF2
  chmod 600 /etc/zju-autologin/config.json
}

if command -v uci >/dev/null 2>&1; then
  /etc/init.d/zju-autologin enable
  /etc/init.d/zju-autologin start
fi
echo "✓ 安装完成: 开机自启 + 崩溃自动重启"
echo "  状态: zju-autologin status | 日志: logread | [systemd] journalctl -u zju-autologin"
