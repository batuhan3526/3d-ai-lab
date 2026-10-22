# MeshFlow (Meta FAIR, non-commercial) — remesh / guided topology clean-up. ~10–12 GB VRAM.
ENGINE_DIR=meshflow
ENGINE_URL=https://github.com/facebookresearch/meshflow
ENGINE_COMMIT=485f44600a0147b948f804552e8374615a1df72c
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu128
ENGINE_GATED=1
ENGINE_WORKER=meshflow
ENGINE_CELERY_APP=meshflow_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/meshflow"

engine_weights() {
  hf_get facebook/meshflow "$ENGINE_PATH/ckpt/_hf_meshflow"
  [ -e "$ENGINE_PATH/ckpt/meshflow" ] || ln -s _hf_meshflow/meshflow "$ENGINE_PATH/ckpt/meshflow"
}
