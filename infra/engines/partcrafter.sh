# PartCrafter (MIT; its RMBG matte is non-commercial) — part-aware photo → 3D. ~12 GB VRAM.
ENGINE_DIR=PartCrafter
ENGINE_URL=https://github.com/wgsxm/PartCrafter.git
ENGINE_COMMIT=3d773bf02fad51c7ab31a5615573fec93b287b30
ENGINE_ENV=venv
ENGINE_PYTHON=3.11
ENGINE_TORCH_INDEX=cu124
ENGINE_PIP_ARGS="-f https://data.pyg.org/whl/torch-2.5.1+cu124.html"
ENGINE_WORKER=partcrafter
ENGINE_CELERY_APP=partcrafter_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/PartCrafter"

engine_weights() {
  hf_get wgsxm/PartCrafter "$ENGINE_PATH/pretrained_weights/PartCrafter"
  hf_get briaai/RMBG-1.4 "$ENGINE_PATH/pretrained_weights/RMBG-1.4"
}
