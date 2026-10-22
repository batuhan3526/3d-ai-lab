# VideoMDM (research code) — text → human motion for the mannequin. ~6 GB VRAM.
# Checkpoints ship inside the upstream repo (save/videomdm_ckpts).
ENGINE_DIR=VideoMDM_release
ENGINE_URL=https://github.com/Amir-Mann/VideoMDM_release
ENGINE_COMMIT=6fda4f394fcb287c524d37f247d868271e1dfabd
ENGINE_ENV=venv
ENGINE_PYTHON=3.10
ENGINE_TORCH_INDEX=cu121
ENGINE_WORKER=videomdm
ENGINE_CELERY_APP=videomdm_worker.worker.celery_app
ENGINE_EXTRA_PATH="$ENGINES_DIR/VideoMDM_release"

engine_env() { export PYOPENGL_PLATFORM=egl; }
