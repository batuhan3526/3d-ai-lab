# UltraTex (MIT code; SIGGRAPH Asia 2026) — retexture an existing 3D model from a reference
# image: 6 fixed-camera normal maps + the image → FLUX.2-klein 9B + UltraTex LoRA → 2K
# multi-view albedo baked back onto the model's UV. Geometry is unchanged.
# Weights: FLUX.2-klein-base-9B (BFL licence, request access on Hugging Face), Qwen3-8B
# (Apache-2.0), FLUX.2 VAE (Comfy-Org copy), UltraTex LoRA + decoder (ModelScope).
# The 9B model and the 8B text encoder do not fit one 24 GB card together: with two GPUs
# the text encoder runs on the other one, otherwise on the CPU.
ENGINE_DIR=UltraTex
ENGINE_URL=https://github.com/yiboz2001/UltraTex.git
ENGINE_COMMIT=a726678f3f3631fe2c5e3d1fb4597114784c7a8b
ENGINE_ENV=conda
ENGINE_CONDA_NAME=ultratex
ENGINE_PYTHON=3.12
ENGINE_GATED=1
ENGINE_WORKER=ultratex
ENGINE_CELERY_APP=ultratex_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/UltraTex"

engine_env() {
  export TOKENIZERS_PARALLELISM=false
  # nvdiffrast ilk çalışmada env'in nvcc 12.4'üyle derlenir (JIT). conda-forge CUDA başlıkları
  # targets/…/include'da, libcudart lib/'de; torch ise $CUDA_HOME/include ve lib64'e bakıyor.
  export CUDA_HOME="$CONDA_PREFIX"
  export CPATH="$CONDA_PREFIX/targets/x86_64-linux/include${CPATH:+:$CPATH}"
  export LIBRARY_PATH="$CONDA_PREFIX/lib${LIBRARY_PATH:+:$LIBRARY_PATH}"
  # metin kodlayıcı için ikinci GPU (varsa) görünür olsun
  local n other
  n="$(nvidia-smi -L 2>/dev/null | wc -l)"
  if [ "${n:-1}" -gt 1 ] && [ -n "${CUDA_VISIBLE_DEVICES:-}" ] && [[ "$CUDA_VISIBLE_DEVICES" != *,* ]]; then
    other="$(seq 0 $((n - 1)) | grep -vx "$CUDA_VISIBLE_DEVICES" | head -1)"
    export CUDA_VISIBLE_DEVICES="$CUDA_VISIBLE_DEVICES,$other"
  fi
}

engine_setup_env() { make_conda nvidia::cuda-toolkit=12.4; }

engine_build() {
  export CUDA_HOME="$CONDA_PREFIX" CUDACXX="$CONDA_PREFIX/bin/nvcc"
  export TORCH_CUDA_ARCH_LIST; TORCH_CUDA_ARCH_LIST="$(cuda_arch)"
  # modelscope pkg_resources ister (setuptools 81'de kaldırıldı)
  # deepspeed yalnız eğitim için ve kaynaktan derleniyor (torch'u kurulumda arar) → atla
  local req; req="$(mktemp)"
  grep -v '^deepspeed' "$ENGINE_PATH/requirements.txt" > "$req"
  "$PY" -m pip install -r "$req" modelscope==1.34.0 "setuptools<81" ninja xatlas scipy "trimesh==4.10.1"
  "$PY" -m pip install --no-build-isolation "git+https://github.com/NVlabs/nvdiffrast.git@v0.3.3"
}

engine_weights() {
  local d="$ENGINE_PATH/checkpoints/base/flux2"
  mkdir -p "$d"
  "$PY" - "$d" <<'PY'
import shutil, sys
from huggingface_hub import hf_hub_download, snapshot_download
d = sys.argv[1]
shutil.copy(hf_hub_download("Comfy-Org/Flux-2-Klein-9B", "split_files/vae/flux2-vae.safetensors"), f"{d}/ae.safetensors")
hf_hub_download("black-forest-labs/FLUX.2-klein-base-9B", "flux-2-klein-base-9b.safetensors", local_dir=d)
snapshot_download("Qwen/Qwen3-8B", local_dir=f"{d}/qwen3-8b")
PY
  "$(dirname "$PY")/modelscope" download --model Yibo-Zhang/UltraTex --local_dir "$ENGINE_PATH/checkpoints" \
    --include "flux2/*" "flux2_mr/*"
}
