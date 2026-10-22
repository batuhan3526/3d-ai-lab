#!/usr/bin/env bash
# Stop the services started by start-linux.sh (pid files in run/). Redis is left
# running — it may be shared with other software.
set -uo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUN_DIR="$REPO_ROOT/run"
shopt -s nullglob
pids=("$RUN_DIR"/*.pid)
[ ${#pids[@]} -gt 0 ] || { echo "nothing to stop"; exit 0; }

for f in "${pids[@]}"; do
  pid="$(cat "$f")"
  name="$(basename "$f" .pid)"
  # each service runs in its own process group (setsid) → stop the whole group
  if kill -0 "$pid" 2>/dev/null; then
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    echo "stopping $name ($pid)"
  fi
done

for _ in $(seq 1 15); do
  alive=0
  for f in "${pids[@]}"; do kill -0 "$(cat "$f")" 2>/dev/null && alive=1; done
  [ $alive -eq 0 ] && break
  sleep 1
done
for f in "${pids[@]}"; do
  pid="$(cat "$f")"
  kill -0 "$pid" 2>/dev/null && { kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid"; }
  rm -f "$f"
done
echo "stopped"
