# Cloud API engines (Tripo, Meshy, Rodin, fal, OpenAI, …) — CPU only, no GPU.
# Keys come from .env; engines without a key stay locked in the UI.
ENGINE_FAMILY=cloud
ENGINE_ENV=core
ENGINE_QUEUE=cpu
ENGINE_POOL=threads
ENGINE_WORKER=cloud
ENGINE_CELERY_APP=cloud_worker.worker.celery_app
# motif.bake reuses the GPU-free bake module of the FLUX worker
ENGINE_EXTRA_PATH="$REPO_ROOT/backend/workers/flux_motif/src"
