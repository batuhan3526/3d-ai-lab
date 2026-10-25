# shellcheck shell=bash
# Shared helpers for engine install / run. Sourced by infra/scripts/engine.sh.
#
# Every engine is described by one file, infra/engines/<name>.sh, which sets
# ENGINE_* variables and may define engine_env / engine_build / engine_weights.
# Upstream repos are cloned (pinned) into $ENGINES_DIR/<ENGINE_DIR>; nothing is
# installed outside the repo except what uv/conda cache on their own.

ENGINES_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$ENGINES_LIB_DIR/../.." && pwd)"

say()  { printf '\033[1;36m>> %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m!! %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mxx %s\033[0m\n' "$*" >&2; exit 1; }

# --- .env -------------------------------------------------------------------
# Parsed line by line (not sourced): values with spaces need no quotes, nothing in
# .env is ever executed, and variables already set in the shell take precedence.
load_dotenv() {
  [ -f "$REPO_ROOT/.env" ] || return 0
  local line key val
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line%$'\r'}"
    case "$line" in ''|'#'*) continue ;; esac
    key="${line%%=*}"; val="${line#*=}"
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    case "$val" in \"*\") val="${val:1:-1}" ;; \'*\') val="${val:1:-1}" ;; esac
    [ -n "${!key+x}" ] || export "$key=$val"
  done < "$REPO_ROOT/.env"
}

load_dotenv
ENGINES_DIR="${ENGINES_DIR:-$REPO_ROOT/engines}"
DEFAULT_GPU="${DEFAULT_GPU:-0}"
mkdir -p "$ENGINES_DIR"

# --- engine spec ------------------------------------------------------------
engine_names() {
  local f
  for f in "$ENGINES_LIB_DIR"/*.sh; do
    case "$(basename "$f")" in lib.sh) continue ;; esac
    basename "$f" .sh
  done
}

load_engine() {
  local name="$1" spec="$ENGINES_LIB_DIR/$1.sh"
  [ -f "$spec" ] || die "unknown engine '$name' (see: engine.sh list)"
  # reset spec vars so engines never leak into each other
  unset ENGINE_FAMILY ENGINE_DIR ENGINE_URL ENGINE_COMMIT ENGINE_ENV ENGINE_PYTHON \
        ENGINE_TORCH_INDEX ENGINE_WORKER ENGINE_CELERY_APP ENGINE_EXTRA_PATH \
        ENGINE_POOL ENGINE_QUEUE ENGINE_CONDA_NAME ENGINE_NOTE ENGINE_PIP_ARGS ENGINE_GATED ENGINE_LOCK_SKIP
  unset -f engine_env engine_build engine_weights 2>/dev/null || true
  ENGINE_NAME="$name"
  ENGINE_POOL="solo"
  # shellcheck disable=SC1090
  . "$spec"
  ENGINE_FAMILY="${ENGINE_FAMILY:-$name}"
  ENGINE_PATH="${ENGINE_DIR:+$ENGINES_DIR/$ENGINE_DIR}"
  ENGINE_CONDA_NAME="${ENGINE_CONDA_NAME:-$name}"
}

# Python interpreter of the engine's isolated env (empty if not installed).
engine_python() {
  case "$ENGINE_ENV" in
    venv)  [ -x "$ENGINE_PATH/.venv/bin/python" ] && echo "$ENGINE_PATH/.venv/bin/python" ;;
    conda) local p; p="$(conda_root)/envs/$ENGINE_CONDA_NAME/bin/python"; [ -x "$p" ] && echo "$p" ;;
    core)  [ -x "$REPO_ROOT/.venv/bin/python" ] && echo "$REPO_ROOT/.venv/bin/python" ;;
  esac
}

# Installed = env present AND (no upstream, or its checkout lives in ENGINES_DIR).
# The checkout test keeps unrelated conda envs with the same name from counting.
engine_installed() {
  [ -n "$(engine_python)" ] || return 1
  [ -z "${ENGINE_URL:-}" ] || [ -d "$ENGINE_PATH/.git" ]
}

# --- hardware ---------------------------------------------------------------
# Compute capability of the first visible GPU, e.g. "8.6". Used for CUDA builds.
cuda_arch() {
  if [ -n "${TORCH_CUDA_ARCH_LIST:-}" ]; then echo "$TORCH_CUDA_ARCH_LIST"; return; fi
  command -v nvidia-smi >/dev/null 2>&1 || { echo "8.6"; return; }
  nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -1 | tr -d ' ' || echo "8.6"
}

# CUDA toolkit for source builds: explicit CUDA_HOME, else the dir holding nvcc.
cuda_home() {
  if [ -n "${CUDA_HOME:-}" ]; then echo "$CUDA_HOME"; return; fi
  local nvcc; nvcc="$(command -v nvcc 2>/dev/null || true)"
  [ -n "$nvcc" ] && dirname "$(dirname "$nvcc")" && return
  [ -x /usr/local/cuda/bin/nvcc ] && echo /usr/local/cuda && return
  echo ""
}

require_nvcc() {
  [ -n "$(cuda_home)" ] || die "$ENGINE_NAME needs the CUDA toolkit (nvcc) to build extensions.
   Install it (e.g. 'sudo apt install nvidia-cuda-toolkit' or NVIDIA's CUDA 12.x repo)
   or set CUDA_HOME=/path/to/cuda."
}

# --- source -----------------------------------------------------------------
clone_pinned() {
  [ -n "${ENGINE_URL:-}" ] || return 0
  if [ ! -d "$ENGINE_PATH/.git" ]; then
    say "cloning $ENGINE_URL @ ${ENGINE_COMMIT:0:7}"
    git clone --recursive "$ENGINE_URL" "$ENGINE_PATH"
  fi
  if [ -n "${ENGINE_COMMIT:-}" ]; then
    git -C "$ENGINE_PATH" fetch -q origin "$ENGINE_COMMIT" 2>/dev/null || true
    git -C "$ENGINE_PATH" checkout -q "$ENGINE_COMMIT"
    git -C "$ENGINE_PATH" submodule update -q --init --recursive 2>/dev/null || true
  fi
  local patch="$ENGINES_LIB_DIR/patches/$ENGINE_NAME.patch"
  if [ -f "$patch" ]; then
    if git -C "$ENGINE_PATH" apply --check "$patch" 2>/dev/null; then
      say "applying patches/$ENGINE_NAME.patch"
      git -C "$ENGINE_PATH" apply "$patch"
    elif git -C "$ENGINE_PATH" apply --reverse --check "$patch" 2>/dev/null; then
      echo "   patch already applied"
    else
      die "patches/$ENGINE_NAME.patch does not apply to $ENGINE_PATH"
    fi
  fi
}

# --- environments -----------------------------------------------------------
make_venv() {
  command -v uv >/dev/null 2>&1 || die "uv is required: curl -LsSf https://astral.sh/uv/install.sh | sh"
  [ -x "$ENGINE_PATH/.venv/bin/python" ] || uv venv -q --python "$ENGINE_PYTHON" "$ENGINE_PATH/.venv"
  PY="$ENGINE_PATH/.venv/bin/python"
}

conda_root() {
  if [ -n "${CONDA_ROOT:-}" ]; then echo "$CONDA_ROOT"; return; fi
  if command -v conda >/dev/null 2>&1; then conda info --base 2>/dev/null; return; fi
  echo "$ENGINES_DIR/.miniforge"
}

ensure_conda() {
  local root; root="$(conda_root)"
  if [ ! -x "$root/bin/conda" ]; then
    say "installing Miniforge into $root"
    local inst; inst="$(mktemp -d)/miniforge.sh"
    curl -fsSL "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-$(uname -m).sh" -o "$inst"
    bash "$inst" -b -p "$root"
  fi
  # shellcheck disable=SC1091
  . "$root/etc/profile.d/conda.sh"
}

# make_conda [extra conda packages...] — creates and activates the engine env.
make_conda() {
  ensure_conda
  # nvidia::cuda-toolkit=X sürümü tek başına sabitlemiyor: cuda-version 13.x çözülüp conda-forge'un
  # 13.x nvcc/cudart'ı ve gcc 15 geliyor → torch cuXY ile JIT/kaynak derlemesi kırılıyor.
  # cuda-version=X tüm CUDA paketlerini X'e bağlar; CUDA 12.x nvcc en çok gcc 13 kabul eder
  # (tarif kendi gcc'sini vermediyse 13'e sabitle).
  local a pins=() cuda12="" own_cc=""
  for a in "$@"; do
    case "$a" in
      nvidia::cuda-toolkit=*) pins+=("cuda-version=${a#*=}"); [[ "${a#*=}" == 12* ]] && cuda12=1 ;;
      *gcc*|*gxx*) own_cc=1 ;;
    esac
  done
  [ -n "$cuda12" ] && [ -z "$own_cc" ] && pins+=("conda-forge::gcc=13" "conda-forge::gxx=13")
  conda env list | awk '{print $1}' | grep -qx "$ENGINE_CONDA_NAME" \
    || conda create -y -n "$ENGINE_CONDA_NAME" "python=$ENGINE_PYTHON" "$@" "${pins[@]}"
  conda_activate "$ENGINE_CONDA_NAME"
  PY="$CONDA_PREFIX/bin/python"
}

# conda activate.d betikleri (ör. cuda-nvcc) tanımsız değişken okur → set -u altında patlar.
conda_activate() {
  local had_u=0
  case $- in *u*) had_u=1; set +u ;; esac
  conda activate "$1"
  [ "$had_u" = 1 ] && set -u
  return 0
}

# pip install into the engine env (uv when available — much faster).
pipi() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python "$PY" --index-strategy unsafe-best-match "$@"
  else
    "$PY" -m pip install "$@"
  fi
}

torch_index() { echo "https://download.pytorch.org/whl/${ENGINE_TORCH_INDEX:-cu124}"; }

# Install the frozen, known-good package set (infra/engines/locks/<name>.txt).
# Local/editable builds are filtered out — engine_build() compiles those.
install_lock() {
  local lock="$ENGINES_LIB_DIR/locks/$ENGINE_NAME.txt" tmp
  [ -f "$lock" ] || { warn "no lock file for $ENGINE_NAME"; return 0; }
  tmp="$(mktemp)"
  grep -vE '^\s*(#|-e |$)|@ file://' "$lock" \
    | { if [ -n "${ENGINE_LOCK_SKIP:-}" ]; then grep -vE "$ENGINE_LOCK_SKIP"; else cat; fi; } > "$tmp"
  say "installing locked deps ($(wc -l < "$tmp") packages)"
  # shellcheck disable=SC2086  # ENGINE_PIP_ARGS is intentionally word-split
  pipi --extra-index-url "$(torch_index)" ${ENGINE_PIP_ARGS:-} -r "$tmp"
  rm -f "$tmp"
}

# Packages every worker needs to talk to the gateway (broker + settings + logs).
install_worker_deps() {
  pipi "celery>=5.4" "redis>=5" "pydantic>=2.6" "pydantic-settings>=2.2" \
       structlog python-dotenv sqlalchemy
}

# Build CUDA extensions with the right arch and toolkit.
cuda_build_env() {
  require_nvcc
  export CUDA_HOME; CUDA_HOME="$(cuda_home)"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  export MAX_JOBS="${MAX_JOBS:-$(( $(nproc) / 2 > 0 ? $(nproc) / 2 : 1 ))}"
}

# pip-install a CUDA extension from a git repo (optionally a subdirectory).
# Sources are cached under $ENGINES_DIR/_src so rebuilds don't re-clone.
build_git_ext() {
  local url="$1" name="$2" sub="${3:-}" src="$ENGINES_DIR/_src/$2"
  [ -d "$src" ] || git clone -q --depth 1 --recurse-submodules "$url" "$src"
  say "building $name${sub:+/$sub}"
  pipi --no-build-isolation "$src${sub:+/$sub}"
}

# The TRELLIS-family rasterizers (TRELLIS, Hi3DGen).
build_trellis_exts() {
  cuda_build_env
  pipi setuptools wheel ninja
  build_git_ext https://github.com/NVlabs/nvdiffrast.git nvdiffrast
  build_git_ext https://github.com/autonomousvision/mip-splatting.git mip-splatting \
    submodules/diff-gaussian-rasterization
  build_git_ext https://github.com/JeffreyXiang/diffoctreerast.git diffoctreerast
}

# Download a Hugging Face repo into the engine dir (uses HF_TOKEN for gated ones).
hf_get() {
  local repo="$1" dest="$2"; shift 2
  [ -n "$(ls -A "$dest" 2>/dev/null)" ] && { echo "   weights present: $repo"; return 0; }
  say "downloading $repo → ${dest#"$REPO_ROOT"/}"
  "$PY" - "$repo" "$dest" "$@" <<'PYEOF'
import os, sys
from huggingface_hub import snapshot_download
repo, dest, *patterns = sys.argv[1:]
snapshot_download(repo, local_dir=dest, allow_patterns=patterns or None,
                  token=os.getenv("HF_TOKEN") or None)
PYEOF
}

# --- run --------------------------------------------------------------------
# Exports PYTHONPATH + per-engine env and execs the Celery worker.
run_worker() {
  local gpu="${1:-$DEFAULT_GPU}" queue="${2:-}"
  local py; py="$(engine_python)"
  [ -n "$py" ] || die "$ENGINE_NAME is not installed — run: infra/scripts/engine.sh install $ENGINE_NAME"
  local worker_src="$REPO_ROOT/backend/workers/$ENGINE_WORKER/src"
  export PYTHONPATH="${ENGINE_EXTRA_PATH:+$ENGINE_EXTRA_PATH:}$REPO_ROOT/backend/common/src:$worker_src${PYTHONPATH:+:$PYTHONPATH}"
  export PATH="$(dirname "$py"):$PATH"
  if [ "$ENGINE_ENV" = "conda" ]; then
    export CONDA_PREFIX; CONDA_PREFIX="$(dirname "$(dirname "$py")")"
  fi
  if [ "${ENGINE_QUEUE:-}" = "cpu" ]; then
    queue="${queue:-$ENGINE_FAMILY-cpu}"
  else
    export CUDA_VISIBLE_DEVICES="$gpu"
    queue="${queue:-$ENGINE_FAMILY-gpu$gpu}"
  fi
  if declare -F engine_env >/dev/null; then engine_env; fi
  [ -n "${ENGINE_PATH:-}" ] && cd "$ENGINE_PATH"
  local pool=(-P "$ENGINE_POOL")
  [ "$ENGINE_POOL" = "threads" ] && pool+=(-c 4)
  echo "$ENGINE_NAME worker: queue=$queue ${CUDA_VISIBLE_DEVICES:+gpu=$CUDA_VISIBLE_DEVICES}"
  exec "$py" -m celery -A "$ENGINE_CELERY_APP" worker "${pool[@]}" -l info \
       -Q "$queue" -n "$ENGINE_NAME-$queue@%h"
}
