# TRELLIS (Microsoft, MIT) — text → 3D and photo → 3D. ~10–12 GB VRAM.
ENGINE_DIR=TRELLIS
ENGINE_URL=https://github.com/microsoft/TRELLIS.git
ENGINE_COMMIT=442aa1e1afb9014e80681d3bf604e8d728a86ee7
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu121
ENGINE_PIP_ARGS="-f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html"
ENGINE_WORKER=text_to_3d
ENGINE_CELERY_APP=text_to_3d.trellis_worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/TRELLIS"

engine_env() {
  export ATTN_BACKEND=xformers SPCONV_ALGO=native
  # Turkish prompts are translated on the worker (opus-mt, runs on the same GPU).
  export TRANSLATE_BACKEND="${WORKER_TRANSLATE_BACKEND:-opus}"
}

engine_build() {
  build_trellis_exts
  pipi --no-build-isolation "$ENGINE_PATH/extensions/vox2seq"
}
