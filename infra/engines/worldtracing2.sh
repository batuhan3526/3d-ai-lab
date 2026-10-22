# World Tracing + TRELLIS.2 — textured mode of World Tracing (separate env and queue
# "worldtracing2-gpuN"; the gateway routes mode=trellis2 jobs here).
ENGINE_DIR=TRELLIS.2
ENGINE_FAMILY=worldtracing2
ENGINE_URL=https://github.com/microsoft/TRELLIS.2.git
ENGINE_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd
ENGINE_ENV=conda
ENGINE_CONDA_NAME=trellis2
ENGINE_PYTHON=3.10
ENGINE_GATED=1
ENGINE_WORKER=worldtracing
ENGINE_CELERY_APP=worldtracing_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/world-tracing:$ENGINES_DIR/TRELLIS.2"

engine_env() {
  export CUDA_HOME="$CONDA_PREFIX"
  export ATTN_BACKEND=xformers SPARSE_ATTN_BACKEND=xformers
}

engine_setup_env() { make_conda nvidia::cuda-toolkit=12.4; }

engine_build() {
  [ -d "$ENGINES_DIR/world-tracing/.git" ] \
    || die "install 'worldtracing' first (this mode reuses its checkout)"
  export CUDA_HOME="$CONDA_PREFIX"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  "$PY" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
  local step
  for step in --basic --flash-attn --o-voxel --flexgemm --cumesh --nvdiffrast; do
    ( cd "$ENGINE_PATH" && bash setup.sh "$step" )
  done
  "$PY" -m pip install -e "$ENGINES_DIR/world-tracing[viz,bg,textured-mesh]"
}
