#!/usr/bin/env bash
# One-time setup of the core app: gateway + common + CPU workers (one Python env),
# the FreeSewing pattern service, the frontend, .env and data dirs.
#
#   bash infra/scripts/setup-linux.sh
#
# GPU engines are installed separately, one by one, each into its own env:
#   infra/scripts/engine.sh list
#   infra/scripts/engine.sh install triposr
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

say()  { printf '\n\033[1;36m>> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*"; }

# --- 1. prerequisites -------------------------------------------------------
say "Checking prerequisites"
missing=0
for tool in git curl uv node pnpm; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '   ok: %s\n' "$tool"
  else
    warn "missing: $tool"; missing=1
  fi
done
if [ "$missing" -ne 0 ]; then
  cat <<'EOF'
Install the missing tools first (Debian/Ubuntu shown):
  - git, curl : sudo apt install git curl
  - uv        : curl -LsSf https://astral.sh/uv/install.sh | sh
  - node 18+  : https://nodejs.org (or nvm)
  - pnpm      : npm i -g pnpm   (or: corepack enable)
EOF
  exit 1
fi
if command -v redis-server >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
  echo "   ok: redis-server or docker (broker)"
else
  warn "no redis-server and no docker — install one before starting:"
  warn "  sudo apt install redis-server"
fi
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=index,name,memory.total --format=csv,noheader | sed 's/^/   gpu: /'
else
  warn "nvidia-smi not found — GPU engines need an NVIDIA GPU + driver (cloud engines still work)"
fi

# --- 2. .env ----------------------------------------------------------------
say "Configuring .env"
if [ ! -f .env ]; then
  cp .env.example .env
  tok="$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))' 2>/dev/null || uv run --no-project python -c 'import secrets;print(secrets.token_urlsafe(32))')"
  sed -i "s#^APP_TOKEN=.*#APP_TOKEN=${tok}#" .env
  echo "   wrote .env with a random APP_TOKEN — review DEFAULT_GPU and HF_TOKEN"
else
  echo "   .env exists — left untouched"
fi

# --- 3. data dirs -----------------------------------------------------------
mkdir -p data/{models,projects,uploads,cache,templates,patterns} logs run

# --- 4. Python core (gateway + common + clothsim + cloud) -------------------
say "Installing the Python core with uv"
uv sync --all-packages --extra dev

# --- 5. FreeSewing pattern service (Node) -----------------------------------
say "Installing the FreeSewing pattern service"
( cd backend/services/freesewing && npm ci --no-audit --no-fund --loglevel=error )

# --- 6. frontend ------------------------------------------------------------
say "Installing the frontend"
( cd frontend && pnpm install --frozen-lockfile )

# --- 7. procedural garment templates ----------------------------------------
say "Generating garment templates"
uv run python -m templates_tool.generate >/dev/null && echo "   data/templates ready"

cat <<EOF

$(printf '\033[1;32mCore setup done.\033[0m')
Next:
  1. Optional: Blender for cloth drape / dressing / 3D sewing (CPU):
       infra/scripts/engine.sh install clothsim
  2. Install the GPU engines you want (each in its own env, one at a time):
       infra/scripts/engine.sh list
       infra/scripts/engine.sh install triposr      # light, ~6 GB VRAM
       infra/scripts/engine.sh install trellis      # text → 3D, ~10–12 GB VRAM
  3. Start:  bash infra/scripts/start-linux.sh   → http://localhost:\${FRONTEND_PORT:-3000}
EOF
