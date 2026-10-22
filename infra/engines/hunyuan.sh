# Hunyuan3D-2.1 (Tencent Community license, gated weights) — shape, multi-view and
# textured (PBR) image → 3D. 8–22 GB VRAM depending on the mode.
ENGINE_DIR=hunyuan3d-2.1
ENGINE_URL=https://github.com/Tencent-Hunyuan/Hunyuan3D-2.1.git
ENGINE_COMMIT=82920d643c0dc2f7bfd7255f45f62d386edfe60c
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu124
ENGINE_GATED=1
ENGINE_WORKER=hunyuan
ENGINE_CELERY_APP=hunyuan_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/hunyuan3d-2.1/hy3dshape"

engine_build() {
  cuda_build_env
  pipi setuptools wheel ninja
  pipi --no-build-isolation -e "$ENGINE_PATH/hy3dpaint/custom_rasterizer"
  ( cd "$ENGINE_PATH/hy3dpaint/DifferentiableRenderer" && PATH="$(dirname "$PY"):$PATH" bash compile_mesh_painter.sh )
}
