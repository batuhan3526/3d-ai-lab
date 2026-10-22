# GaussianGPT (research code) — text → 3D Gaussian scene. Builds flash-attn and
# MinkowskiEngine from source (long compile, needs ~16 GB RAM).
ENGINE_DIR=GaussianGPT
ENGINE_URL=https://github.com/nicolasvonluetzow/GaussianGPT.git
ENGINE_COMMIT=0615470a5ff359c676408e9ae42036d534d04a43
ENGINE_ENV=conda
ENGINE_PYTHON=3.10
ENGINE_WORKER=gaussiangpt
ENGINE_CELERY_APP=gaussiangpt_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/GaussianGPT"

engine_setup_env() {
  make_conda nvidia::cuda-toolkit=12.9 conda-forge::glm conda-forge::openblas ninja \
    conda-forge::gcc_linux-64=11 conda-forge::gxx_linux-64=11
  [ -e "$CONDA_PREFIX/lib64" ] || ln -s "$CONDA_PREFIX/lib" "$CONDA_PREFIX/lib64"
}

engine_build() {
  export CUDA_HOME="$CONDA_PREFIX"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  export CC="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-cc" CXX="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-c++"
  "$PY" -m pip install torch==2.8.0 torchvision torchaudio --index-url https://download.pytorch.org/whl/cu129
  ( cd "$ENGINE_PATH" && "$PY" -m pip install --no-build-isolation -r requirements.txt )
  "$PY" -c "import flash_attn" 2>/dev/null || {
    local src="$ENGINES_DIR/_src/flash-attention"
    [ -d "$src" ] || git clone -q --depth 1 --branch v2.8.2 https://github.com/Dao-AILab/flash-attention.git "$src"
    ( cd "$src" && FLASH_ATTN_CUDA_ARCHS="$(cuda_arch | tr -d .)" MAX_JOBS="${MAX_JOBS:-6}" NVCC_THREADS=2 "$PY" setup.py install )
  }
  "$PY" -c "import MinkowskiEngine" 2>/dev/null || {
    local src="$ENGINES_DIR/_src/MinkowskiEngine"
    [ -d "$src" ] || git clone -q --branch cuda12-compat https://github.com/alpsaur/MinkowskiEngine.git "$src"
    ( cd "$src" && "$PY" setup.py install --blas=openblas \
        --blas_include_dirs="$CONDA_PREFIX/include" --blas_library_dirs="$CONDA_PREFIX/lib" )
  }
}

engine_weights() {
  mkdir -p "$ENGINE_PATH/checkpoints"
  local f
  for f in vqvae_vfront.ckpt gpt_vfront.ckpt; do
    [ -f "$ENGINE_PATH/checkpoints/$f" ] || curl -fL -o "$ENGINE_PATH/checkpoints/$f" \
      "https://kaldir.vc.cit.tum.de/gaussiangpt/$f"
  done
}
