# Hi3DGen (Stable-X, MIT) — photo → high-detail geometry via normal maps. ~14 GB VRAM.
ENGINE_DIR=Hi3DGen
ENGINE_URL=https://github.com/Stable-X/Hi3DGen.git
ENGINE_COMMIT=24b7727f99d026efc63373d59977521fa3cbdb6a
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu121
ENGINE_PIP_ARGS="-f https://nvidia-kaolin.s3.us-east-2.amazonaws.com/torch-2.4.0_cu121.html"
ENGINE_WORKER=hi3dgen
ENGINE_CELERY_APP=hi3dgen_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/Hi3DGen"

engine_env() {
  export ATTN_BACKEND=xformers SPARSE_BACKEND=spconv SPCONV_ALGO=native
}

engine_build() { build_trellis_exts; }

engine_weights() {
  hf_get Stable-X/yoso-normal-v1-8-1 "$ENGINE_PATH/weights/yoso-normal-v1-8-1"
}
