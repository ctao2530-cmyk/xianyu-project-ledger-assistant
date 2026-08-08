#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
RELAY_PORT=${WECOM_RELAY_PORT:-8787}

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "未找到 cloudflared。请从 Cloudflare 官方网站安装后再运行此脚本。" >&2
  echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2
  exit 1
fi

if ! curl --fail --silent --max-time 3 http://127.0.0.1:8877/api/health >/dev/null; then
  echo "鱼答后端尚未在 127.0.0.1:8877 运行。" >&2
  exit 1
fi

cleanup() {
  if [ -n "${RELAY_PID:-}" ]; then
    kill "$RELAY_PID" 2>/dev/null || true
    wait "$RELAY_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

cd "$PROJECT_DIR"
"$PROJECT_DIR/.venv/bin/uvicorn" backend.app.callback_relay:app \
  --host 127.0.0.1 --port "$RELAY_PORT" --no-access-log &
RELAY_PID=$!

echo "正在启动仅暴露 /wechat/callback 的测试转发器。"
echo "Cloudflare 输出 HTTPS 地址后，请在末尾追加 /wechat/callback。"
echo "这是临时测试隧道；终端关闭后地址失效，正式使用请配置命名隧道。"
cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$RELAY_PORT"
