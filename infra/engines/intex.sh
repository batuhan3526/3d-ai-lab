# InTeX (MIT) — full and region-brush re-texturing. ~8 GB VRAM.
ENGINE_DIR=InTeX
ENGINE_URL=https://github.com/ashawkey/InTeX.git
ENGINE_COMMIT=6669e4c5ffd025a8ea2c571d81989d1a5c335ab4
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu121
ENGINE_LOCK_SKIP='^nvdiffrast'
ENGINE_WORKER=intex
ENGINE_CELERY_APP=intex_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/InTeX"

engine_env() { export TRANSLATE_BACKEND="${WORKER_TRANSLATE_BACKEND:-opus}"; }

engine_build() {
  cuda_build_env
  pipi setuptools wheel ninja
  pipi --no-build-isolation \
    "git+https://github.com/NVlabs/nvdiffrast.git@253ac4fcea7de5f396371124af597e6cc957bfae"
}
