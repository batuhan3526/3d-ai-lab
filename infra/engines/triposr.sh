# TripoSR (VAST / Stability, MIT) — fastest single photo → 3D (~4 s). ~6 GB VRAM.
ENGINE_DIR=TripoSR
ENGINE_URL=https://github.com/VAST-AI-Research/TripoSR.git
ENGINE_COMMIT=d26e33181947bbbc4c6fc0f5734e1ec6c080956e
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu124
ENGINE_LOCK_SKIP='^torchmcubes'
ENGINE_WORKER=triposr
ENGINE_CELERY_APP=triposr_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/TripoSR"

engine_build() {
  cuda_build_env
  pipi scikit-build-core cmake ninja pybind11 setuptools wheel
  CMAKE_PREFIX_PATH="$("$PY" -c 'import torch;print(torch.utils.cmake_prefix_path)')" \
    pipi --no-build-isolation \
    "git+https://github.com/tatsy/torchmcubes.git@3381600ddc3d2e4d74222f8495866be5fafbace4"
}
