# Hi3D v1.0 (OCEANO HK, Hi3D Open License 1.0 — commercial use OK with "Powered by Hi3D 1.0"
# attribution; separate licence above 200k MAU / $1M monthly revenue) — refines an existing
# coarse mesh into high-resolution geometry, conditioned on the reference photo (Sparc3D).
# Geometry only: run a texturing step (UltraTex) afterwards. Not the same project as Hi3DGen.
# Weights are open (hi3d-official/Hi3Dv1.0, 7.7 GB) + DINOv2-large + CLIP ViT-L on first use.
ENGINE_DIR=Hi3D
ENGINE_URL=https://github.com/hi3d-official/Hi3Dv1.0.git
ENGINE_COMMIT=13657ad09afaa92e350b461a1cd66399e44a59c4
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_WORKER=hi3d
ENGINE_CELERY_APP=hi3d_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/Hi3D"

engine_build() {
  # upstream'in ölçülmüş yığını (docker/constraints.txt); flash-attn kaynaktan ~1 saat
  # derleniyor → aynı sürümün resmi tekerleği
  pipi torch==2.5.0 torchvision==0.20.0 --index-url "$(torch_index)"
  pipi "https://github.com/Dao-AILab/flash-attention/releases/download/v2.7.4.post1/flash_attn-2.7.4.post1+cu12torch2.5cxx11abiFALSE-cp310-cp310-linux_x86_64.whl"
  pipi -c "$ENGINE_PATH/docker/constraints.txt" --extra-index-url "$(torch_index)" \
       -e "$ENGINE_PATH[inference]" xatlas setuptools   # triton çekirdek derlerken setuptools ister
}

engine_weights() {
  hf_get hi3d-official/Hi3Dv1.0 "$ENGINE_PATH/weights" \
    model_index.json "scheduler/*" "vae/*" "transformer_512/*" "transformer_1024/*"
  "$PY" - <<'PY'
from huggingface_hub import snapshot_download
for r in ("facebook/dinov2-large", "openai/clip-vit-large-patch14"):
    snapshot_download(r, allow_patterns=["*.json", "*.safetensors", "*.txt"])
PY
}
