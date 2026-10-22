# Stable Fast 3D (Stability Community license, gated weights) — photo → 3D + PBR. ~7 GB VRAM.
ENGINE_DIR=stable-fast-3d
ENGINE_URL=https://github.com/Stability-AI/stable-fast-3d.git
ENGINE_COMMIT=ff21fc491b4dc5314bf6734c7c0dabd86b5f5bb2
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu121
ENGINE_GATED=1
ENGINE_WORKER=sf3d
ENGINE_CELERY_APP=sf3d_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/stable-fast-3d"

engine_build() {
  cuda_build_env
  pipi "setuptools==69.5.1" wheel ninja
  pipi --no-build-isolation "$ENGINE_PATH/texture_baker/" "$ENGINE_PATH/uv_unwrapper/"
}
