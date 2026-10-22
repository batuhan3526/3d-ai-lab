#!/usr/bin/env bash
# Install, check and run 3D engine workers.
#
#   infra/scripts/engine.sh list                 # engines + install state
#   infra/scripts/engine.sh install triposr      # clone (pinned) + env + build + weights
#   infra/scripts/engine.sh install trellis hi3dgen
#   infra/scripts/engine.sh check triposr        # import the worker in its env
#   infra/scripts/engine.sh run triposr [GPU]    # foreground Celery worker
#
# Each engine gets its own isolated env (uv venv or conda) because the upstream
# torch/CUDA pins are mutually incompatible. Specs live in infra/engines/<name>.sh.
# GPU defaults to DEFAULT_GPU from .env (0 on a single-GPU machine).
set -euo pipefail
# shellcheck disable=SC1091
. "$(cd "$(dirname "${BASH_SOURCE[0]}")/../engines" && pwd)/lib.sh"

cmd_list() {
  printf '%-14s %-9s %-6s %s\n' ENGINE STATE ENV QUEUE
  local n state q
  for n in $(engine_names); do
    load_engine "$n"
    state="missing"; engine_installed && state="installed"
    if [ "${ENGINE_QUEUE:-}" = "cpu" ]; then q="$ENGINE_FAMILY-cpu"; else q="$ENGINE_FAMILY-gpu$DEFAULT_GPU"; fi
    printf '%-14s %-9s %-6s %s%s\n' "$n" "$state" "$ENGINE_ENV" "$q" "${ENGINE_GATED:+  (gated: needs HF_TOKEN + accepted license)}"
  done
}

install_one() {
  load_engine "$1"
  say "=== $ENGINE_NAME ==="
  [ -n "${ENGINE_PATH:-}" ] && mkdir -p "$ENGINE_PATH"
  clone_pinned
  case "$ENGINE_ENV" in
    venv)
      make_venv
      install_lock
      install_worker_deps
      ;;
    conda)
      if declare -F engine_setup_env >/dev/null; then engine_setup_env; else make_conda; fi
      ;;
    core)
      [ -x "$REPO_ROOT/.venv/bin/python" ] || die "core env missing — run infra/scripts/setup-linux.sh first"
      PY="$REPO_ROOT/.venv/bin/python"
      ;;
  esac
  if declare -F engine_build >/dev/null; then engine_build; fi
  [ "$ENGINE_ENV" = "conda" ] && install_worker_deps
  if declare -F engine_weights >/dev/null; then
    if [ -n "${ENGINE_GATED:-}" ] && [ -z "${HF_TOKEN:-}" ]; then
      warn "$ENGINE_NAME weights are gated: accept the license on huggingface.co and set HF_TOKEN in .env, then: engine.sh weights $ENGINE_NAME"
    else
      engine_weights
    fi
  fi
  [ -n "${ENGINE_NOTE:-}" ] && warn "$ENGINE_NAME: $ENGINE_NOTE"
  check_one "$ENGINE_NAME"
}

weights_one() {
  load_engine "$1"
  PY="$(engine_python)"; [ -n "$PY" ] || die "$1 is not installed"
  declare -F engine_weights >/dev/null && engine_weights || echo "   $1 downloads its weights on first use"
}

# Import the worker module inside the engine env (no GPU work, no weights loaded).
check_one() {
  load_engine "$1"
  local py; py="$(engine_python)"
  [ -n "$py" ] || { warn "$1: not installed"; return 1; }
  local module="${ENGINE_CELERY_APP%.celery_app}"
  if ( export APP_TOKEN="${APP_TOKEN:-check}"
       export PYTHONPATH="${ENGINE_EXTRA_PATH:+$ENGINE_EXTRA_PATH:}$REPO_ROOT/backend/common/src:$REPO_ROOT/backend/workers/$ENGINE_WORKER/src"
       [ -n "${ENGINE_PATH:-}" ] && cd "$ENGINE_PATH"
       "$py" -c "import importlib; importlib.import_module('$module')" ) >/dev/null 2>&1; then
    printf '\033[1;32m   ok: %s imports cleanly\033[0m\n' "$1"
  else
    warn "$1: worker import failed — run 'engine.sh run $1' to see the error"
    return 1
  fi
}

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

[ $# -ge 1 ] || usage 1
action="$1"; shift
case "$action" in
  list)    cmd_list ;;
  install) [ $# -ge 1 ] || usage 1
           if [ "$1" = all ]; then set -- $(engine_names); fi
           for e in "$@"; do install_one "$e"; done ;;
  weights) for e in "$@"; do weights_one "$e"; done ;;
  check)   [ $# -ge 1 ] || set -- $(engine_names)
           rc=0; for e in "$@"; do check_one "$e" || rc=1; done; exit $rc ;;
  run)     [ $# -ge 1 ] || usage 1
           load_engine "$1"; run_worker "${2:-$DEFAULT_GPU}" "${3:-}" ;;
  -h|--help|help) usage ;;
  *) usage 1 ;;
esac
