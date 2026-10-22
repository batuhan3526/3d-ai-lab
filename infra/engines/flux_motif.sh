# FLUX.1-dev motif / decal generator (FLUX non-commercial license, gated). ~16 GB VRAM
# with 8-bit weights. No upstream clone — the worker code lives in this repo.
ENGINE_DIR=flux
ENGINE_FAMILY=flux
ENGINE_ENV=venv
ENGINE_PYTHON=3.12
ENGINE_TORCH_INDEX=cu121
ENGINE_GATED=1
ENGINE_WORKER=flux_motif
ENGINE_CELERY_APP=flux_motif_worker.worker.celery_app

engine_env() { export TRANSLATE_BACKEND="${WORKER_TRANSLATE_BACKEND:-opus}"; }

engine_weights() {
  local w="$ENGINES_DIR/models/esrgan/RealESRGAN_x4plus.pth"
  [ -f "$w" ] && return 0
  mkdir -p "$(dirname "$w")"
  say "downloading Real-ESRGAN x4 (BSD-3) for upscaling"
  curl -fsSL -o "$w" \
    https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
}
