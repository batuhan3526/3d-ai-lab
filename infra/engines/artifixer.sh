# ArtiFixer (NVIDIA research code) — repairs artifacts in 3D scans. 14B model; on a
# 24 GB card it runs with CPU offload (ARTIFIXER_CPU_OFFLOAD=1, slow but fits).
ENGINE_DIR=ArtiFixer
ENGINE_URL=https://github.com/nv-tlabs/ArtiFixer.git
ENGINE_COMMIT=8e882d6884cea08daa58d5c8d4552d0142e617f1
ENGINE_ENV=conda
ENGINE_PYTHON=3.12
ENGINE_WORKER=artifixer
ENGINE_CELERY_APP=artifixer_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/ArtiFixer"
ENGINE_NOTE="checkpoint (checkpoints/artifixer-14b.pt, ~68 GB) must be obtained from the upstream project page"

engine_env() {
  export ARTIFIXER_REPO="$ENGINE_PATH"
  export ARTIFIXER_CPU_OFFLOAD="${ARTIFIXER_CPU_OFFLOAD:-1}"
}

engine_setup_env() {
  make_conda nvidia::cuda-toolkit=12.8 ninja cmake \
    conda-forge::gcc_linux-64=11 conda-forge::gxx_linux-64=11
  [ -e "$CONDA_PREFIX/lib64" ] || ln -s "$CONDA_PREFIX/lib" "$CONDA_PREFIX/lib64"
}

engine_build() {
  export CUDA_HOME="$CONDA_PREFIX"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  export CC="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-cc" CXX="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-c++"
  "$PY" -m pip install torch==2.11.0 torchvision --index-url https://download.pytorch.org/whl/cu128
  ( cd "$ENGINE_PATH/thirdparty/3DGRUT-ArtiFixer" \
    && "$PY" -m pip install ninja wheel setuptools \
    && "$PY" -m pip install --no-build-isolation -r requirements.txt \
    && bash scripts/install_slangc.sh "$CONDA_PREFIX" \
    && "$PY" -m pip install --no-build-isolation -e . )
  "$PY" -m pip install accelerate==1.13.0 diffusers==0.37.1 transformers==5.5.0 ftfy \
    einops scipy tqdm Pillow matplotlib opencv-python-headless pyyaml torchmetrics \
    imageio-ffmpeg h5py av torch-fidelity git+https://github.com/microsoft/MoGe.git
}
