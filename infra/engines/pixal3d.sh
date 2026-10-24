# Pixal3D (TencentARC, MIT; SIGGRAPH 2026) — pixel-aligned photo → textured 3D on the
# TRELLIS.2 backbone. Most faithful silhouette/proportions of the open models. ~12 GB VRAM
# in low-VRAM mode (default here). Gated input: facebook/dinov3 image encoder (request
# access on Hugging Face). Camera is estimated with MoGe-2.
ENGINE_DIR=Pixal3D
ENGINE_URL=https://github.com/TencentARC/Pixal3D.git
ENGINE_COMMIT=f7cf38429b0bd264f1995f0f8743a88b1c728b94
ENGINE_ENV=conda
ENGINE_CONDA_NAME=pixal3d
ENGINE_PYTHON=3.10
ENGINE_GATED=1
ENGINE_WORKER=pixal3d
ENGINE_CELERY_APP=pixal3d_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/Pixal3D"

engine_env() {
  export CUDA_HOME="$CONDA_PREFIX"
  export ATTN_BACKEND=xformers SPARSE_ATTN_BACKEND=xformers
}

engine_setup_env() { make_conda nvidia::cuda-toolkit=12.4; }

engine_build() {
  # Pixal3D runs on the TRELLIS.2 stack (o_voxel, flex_gemm, cumesh, nvdiffrast).
  [ -d "$ENGINES_DIR/TRELLIS.2/.git" ] || die "install 'trellis2' first (its setup.sh builds the shared stack)"
  export CUDA_HOME="$CONDA_PREFIX"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  "$PY" -m pip install torch==2.6.0 torchvision==0.21.0 --index-url https://download.pytorch.org/whl/cu124
  local step
  for step in --basic --o-voxel --flexgemm --cumesh --nvdiffrast; do
    ( cd "$ENGINES_DIR/TRELLIS.2" && bash setup.sh "$step" )
  done
  # MoGe pins an older trimesh than Pixal3D's requirements → install it without deps
  grep -v MoGe "$ENGINE_PATH/requirements.txt" > "$ENGINE_PATH/.requirements-nomoge.txt"
  "$PY" -m pip install -r "$ENGINE_PATH/.requirements-nomoge.txt" xformers==0.0.29.post2
  "$PY" -m pip install --no-deps "git+https://github.com/microsoft/MoGe.git" \
    "utils3d_moge @ git+https://github.com/EasternJournalist/utils3d-moge.git@62f09d58509485564e24d5d9f6aac9ee9ebc0c37"
  NATTEN_CUDA_ARCH="$TORCH_CUDA_ARCH_LIST" NATTEN_N_WORKERS="${MAX_JOBS:-6}" \
    "$PY" -m pip install natten==0.21.0 --no-build-isolation
  "$PY" -m pip install https://github.com/LDYang694/Storages/releases/download/20260430/utils3d-0.0.2-py3-none-any.whl
}
