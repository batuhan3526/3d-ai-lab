# FaceAnything (research code) — face photo → 4D head. GPU memory varies.
ENGINE_DIR=FaceAnything
ENGINE_URL=https://github.com/kocasariumut/FaceAnything.git
ENGINE_COMMIT=10c1a8d65d8268fe7bc22e23c44377326c2b13e8
ENGINE_ENV=venv
ENGINE_PYTHON=3.11
ENGINE_TORCH_INDEX=cu128
ENGINE_WORKER=faceanything
ENGINE_CELERY_APP=faceanything_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/FaceAnything/src"

engine_build() { pipi -e "$ENGINE_PATH"; }

engine_weights() {
  hf_get UmutKocasari/FaceAnything "$ENGINE_PATH/checkpoints" checkpoint.pt
}
