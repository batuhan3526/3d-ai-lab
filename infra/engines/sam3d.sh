# SAM 3D Objects (Meta SAM license, gated weights) — real photo → textured 3D. ~24 GB VRAM.
# Uses upstream's own conda environment file (pytorch3d, kaolin, gsplat pins).
ENGINE_DIR=SAM3D-Objects
ENGINE_URL=https://github.com/facebookresearch/sam-3d-objects
ENGINE_COMMIT=81a82373a3a7f4cbb00bd5b32aaf6b4d0f659ddd
ENGINE_ENV=conda
ENGINE_CONDA_NAME=sam3d-objects
ENGINE_PYTHON=3.11
ENGINE_GATED=1
ENGINE_WORKER=sam3d
ENGINE_CELERY_APP=sam3d_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/SAM3D-Objects:$ENGINES_DIR/SAM3D-Objects/notebook"

engine_setup_env() {
  ensure_conda
  conda env list | awk '{print $1}' | grep -qx "$ENGINE_CONDA_NAME" \
    || conda env create -n "$ENGINE_CONDA_NAME" -f "$ENGINE_PATH/environments/default.yml"
  conda activate "$ENGINE_CONDA_NAME"
  PY="$CONDA_PREFIX/bin/python"
}

engine_build() {
  cd "$ENGINE_PATH"
  PIP_EXTRA_INDEX_URL="https://pypi.ngc.nvidia.com https://download.pytorch.org/whl/cu121" \
    "$PY" -m pip install -e ".[dev]" -e ".[p3d]"
  PIP_FIND_LINKS="https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.5.1_cu121.html" \
    "$PY" -m pip install -e ".[inference]"
  if [ -x ./patching/hydra ]; then ./patching/hydra; fi
  export CUDA_HOME="$CONDA_PREFIX"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  "$PY" -m pip install rembg onnxruntime "numpy==1.26.4" "scikit-image==0.23.1"
  "$PY" -m pip install --no-build-isolation "git+https://github.com/NVlabs/nvdiffrast.git"
  build_git_ext https://github.com/autonomousvision/mip-splatting.git mip-splatting \
    submodules/diff-gaussian-rasterization
}

engine_weights() {
  local ck="$ENGINE_PATH/checkpoints"
  [ -f "$ck/hf/pipeline.yaml" ] && { echo "   weights present"; return 0; }
  hf_get facebook/sam-3d-objects "$ck/hf-download"
  mv "$ck/hf-download/checkpoints" "$ck/hf" && rm -rf "$ck/hf-download"
}
