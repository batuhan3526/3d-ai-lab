# TRELLIS.2 (Microsoft, MIT) — photo → textured 3D with OPEN surfaces (garments keep
# their arm/neck openings). ~24 GB VRAM. Gated inputs: facebook/dinov3 image encoder
# (request access on Hugging Face). Background removal uses the open BiRefNet.
ENGINE_DIR=TRELLIS.2
ENGINE_URL=https://github.com/microsoft/TRELLIS.2.git
ENGINE_COMMIT=75fbf0183001ed9876c8dbb35de6b68552ee08bd
ENGINE_ENV=conda
ENGINE_CONDA_NAME=trellis2
ENGINE_PYTHON=3.10
ENGINE_GATED=1
ENGINE_WORKER=trellis2
ENGINE_CELERY_APP=trellis2_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/TRELLIS.2"

engine_env() {
  export CUDA_HOME="$CONDA_PREFIX"
  export ATTN_BACKEND=xformers SPARSE_ATTN_BACKEND=xformers
}

engine_setup_env() { make_conda nvidia::cuda-toolkit=12.4; }

engine_build() {
  export CUDA_HOME="$CONDA_PREFIX"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  "$PY" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
  local step
  for step in --basic --o-voxel --flexgemm --cumesh --nvdiffrast; do
    ( cd "$ENGINE_PATH" && bash setup.sh "$step" )
  done
  # transformers 5.x DINOv3 katmanlarını taşıdı; TRELLIS.2 4.x yapısını bekler
  "$PY" -m pip install "transformers==4.57.3" xformers==0.0.29.post2
}

