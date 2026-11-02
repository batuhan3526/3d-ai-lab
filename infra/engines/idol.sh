# Idol (speridlabs, Apache-2.0) — one photo → 3D Gaussian splat (up to 1M Gaussians) in seconds.
# Pure PyTorch: no CUDA extensions to build. ~7 GB VRAM peak. The worker also turns the splat
# into a vertex-coloured mesh (Poisson) so the result works like every other engine's mesh.glb.
# Gated input: facebook/dinov3-vith16plus image encoder (request access on Hugging Face).
# The FLUX.2 VAE is read from the open FLUX.2-klein-4B repo (Apache-2.0) instead of the gated
# FLUX.2-dev repo the upstream config names — it is the same FLUX.2 VAE.
ENGINE_DIR=Idol
ENGINE_URL=https://github.com/speridlabs/idol-sdk.git
ENGINE_COMMIT=4702a7f00850e34b6e83a2170cc123c3e9570744
ENGINE_ENV=venv
ENGINE_PYTHON=3.11
ENGINE_TORCH_INDEX=cu124
ENGINE_WORKER=idol
ENGINE_CELERY_APP=idol_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/Idol"
ENGINE_NOTE="needs Hugging Face access to facebook/dinov3-vith16plus-pretrain-lvd1689m (gated)"

engine_build() {
  # torch is pinned in the same resolve: idol-sdk only asks torch>=2.5 and PyPI's newest (cu13x)
  # segfaults on CUDA init under WSL with the current driver.
  pipi --extra-index-url "$(torch_index)" torch==2.6.0 torchvision==0.21.0 -e "$ENGINE_PATH" \
    "diffusers>=0.36" "transformers>=4.56,<5" open3d==0.19.0 "trimesh>=4.4" scipy scikit-image accelerate
}

engine_weights() {
  # Idol's own weights are public (Apache-2.0); the encoders download on first use (HF cache).
  hf_get speridlabs/idol "$ENGINE_PATH/weights" config.json "*.safetensors"
}
