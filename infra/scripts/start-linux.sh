#!/usr/bin/env bash
# Start everything: Redis (if needed) → gateway → frontend → engine workers.
#
#   bash infra/scripts/start-linux.sh          # start, return to the shell
#   bash infra/scripts/stop-linux.sh           # stop what this script started
#
# Workers: ENABLED_ENGINES in .env ("auto" = every installed engine + clothsim + cloud).
# All GPU workers bind DEFAULT_GPU (0 on a single-GPU machine). Logs → logs/,
# pid files → run/. Re-running is safe: already-running services are skipped.
set -uo pipefail
# shellcheck disable=SC1091
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/../engines" && pwd)/lib.sh"
cd "$REPO_ROOT"

GATEWAY_HOST="${GATEWAY_HOST:-0.0.0.0}"
GATEWAY_PORT="${GATEWAY_PORT:-9000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
RUN_DIR="$REPO_ROOT/run"
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$RUN_DIR" "$LOG_DIR"

[ -x "$REPO_ROOT/.venv/bin/python" ] || die "core env missing — run: bash infra/scripts/setup-linux.sh"
[ "${APP_TOKEN:-CHANGE_ME_TO_RANDOM_32_BYTES}" != "CHANGE_ME_TO_RANDOM_32_BYTES" ] \
  || die "set APP_TOKEN in .env (setup-linux.sh generates one)"

running() { local f="$RUN_DIR/$1.pid"; [ -f "$f" ] && kill -0 "$(cat "$f")" 2>/dev/null; }

# start <name> <command...> — background, own process group, pid + log files.
start() {
  local name="$1"; shift
  if running "$name"; then echo "   $name already running (pid $(cat "$RUN_DIR/$name.pid"))"; return; fi
  setsid "$@" > "$LOG_DIR/$name.log" 2>&1 < /dev/null &
  echo $! > "$RUN_DIR/$name.pid"
  echo "   $name → logs/$name.log"
}

redis_ok() { "$REPO_ROOT/.venv/bin/python" - "$REDIS_URL" <<'PY' >/dev/null 2>&1
import sys, redis
redis.Redis.from_url(sys.argv[1], socket_connect_timeout=2).ping()
PY
}

# --- Redis --------------------------------------------------------------------
say "Redis ($REDIS_URL)"
if redis_ok; then
  echo "   up"
elif command -v redis-server >/dev/null 2>&1; then
  redis-server --port "$(echo "$REDIS_URL" | sed -E 's#.*:([0-9]+)(/.*)?$#\1#')" \
    --bind 127.0.0.1 --save "" --appendonly no --daemonize yes >/dev/null
  sleep 1; redis_ok && echo "   started redis-server" || die "redis-server did not come up"
elif command -v docker >/dev/null 2>&1; then
  docker compose up -d redis >/dev/null && sleep 2
  redis_ok && echo "   started redis (docker compose)" || die "docker redis did not come up"
else
  die "Redis not reachable and neither redis-server nor docker is installed.
   Install one: sudo apt install redis-server   (or Docker)"
fi

# --- gateway + frontend -------------------------------------------------------
say "Gateway :$GATEWAY_PORT"
start gateway "$REPO_ROOT/.venv/bin/uvicorn" gateway.main:app \
  --app-dir "$REPO_ROOT/backend/gateway/src" --host "$GATEWAY_HOST" --port "$GATEWAY_PORT"

say "Frontend :$FRONTEND_PORT"
command -v pnpm >/dev/null 2>&1 || die "pnpm not found (npm i -g pnpm)"
start frontend bash -c "cd '$REPO_ROOT/frontend' && exec pnpm dev"

# --- engine workers -----------------------------------------------------------
say "Engine workers (GPU $DEFAULT_GPU)"
if [ "${ENABLED_ENGINES:-auto}" = "auto" ]; then
  engines=""
  for n in $(engine_names); do load_engine "$n"; engine_installed && engines="$engines $n"; done
else
  engines="$ENABLED_ENGINES"
fi
for n in $engines; do
  load_engine "$n"
  if ! engine_installed; then warn "$n not installed — skipped (engine.sh install $n)"; continue; fi
  start "worker-$n" "$REPO_ROOT/infra/scripts/engine.sh" run "$n" "$DEFAULT_GPU"
done
[ -n "${engines// /}" ] || warn "no engines installed yet — see: infra/scripts/engine.sh list"

# --- health -------------------------------------------------------------------
say "Waiting for the gateway"
for _ in $(seq 1 60); do
  curl -fs -m 2 "http://localhost:$GATEWAY_PORT/health" >/dev/null 2>&1 && break
  sleep 1
done
if curl -fs -m 2 "http://localhost:$GATEWAY_PORT/health" >/dev/null 2>&1; then
  echo "   gateway OK"
else
  warn "gateway not answering yet — check logs/gateway.log"
fi

LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
cat <<EOF

$(printf '\033[1;32m3D AI Lab is up.\033[0m')
  Local   → http://localhost:${FRONTEND_PORT}
  LAN     → http://${LAN_IP:-<this-machine-ip>}:${FRONTEND_PORT}
  Gateway → http://localhost:${GATEWAY_PORT}/health
  Stop    → bash infra/scripts/stop-linux.sh
EOF
