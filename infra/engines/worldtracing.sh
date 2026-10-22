# World Tracing (CC BY-NC-ND) — photo → 3D (Poisson mesh). ~12 GB VRAM.
ENGINE_DIR=world-tracing
ENGINE_URL=https://github.com/haoz19/world-tracing
ENGINE_COMMIT=f4745189aad54b46e459f8e22ec76ee2d7d337e5
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu128
ENGINE_GATED=1
ENGINE_WORKER=worldtracing
ENGINE_CELERY_APP=worldtracing_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/world-tracing"

engine_build() { pipi -e "$ENGINE_PATH[viz,bg,textured-mesh]"; }

engine_weights() {
  hf_get haoz19/object-model-6layer "$ENGINE_PATH/checkpoints/object-6layer"
}
