# Architecture

3D AI Lab is a local, GPU-backed pipeline that turns images or prompts into editable
textured 3D models. It has three moving parts: a **frontend**, a **gateway**, and a
pool of **GPU workers** coordinated through **Redis**.

```
┌──────────────────────────┐
│  Frontend (Vite :3000)   │  React + TypeScript + three.js (@react-three/fiber, drei)
│  /api  ──proxy──►         │  Vite proxies /api to the gateway (so browsers only need :3000)
└────────────┬─────────────┘
             │ REST
┌────────────▼─────────────┐
│  Gateway (FastAPI :9000)  │  projects, auth (bearer token), job dispatch, asset serving
└────────────┬─────────────┘
             │ enqueue (Celery)
        ┌────▼────┐
        │  Redis  │  broker + result backend          
        └────┬────┘
             │ one queue per engine
┌────────────▼─────────────────────────────────────────────┐
│  GPU workers — each loads ONE model family and drains its │
│  queue: image→3D, multi-view→3D, texturing, decals        │
└────────────┬─────────────────────────────────────────────┘
             ▼
      data/  →  projects, uploads, templates, generated meshes + thumbnails
```

## Request lifecycle

1. The user uploads photo(s) or enters a prompt in the frontend.
2. The frontend calls the gateway (`/api/...`, proxied to `:9000`).
3. The gateway creates/updates a **project**, then enqueues a **job** onto the Redis
   queue for the chosen engine.
4. The matching **worker** picks up the job, runs the model on the GPU, and writes
   the resulting mesh + textures into `data/`.
5. The frontend polls the **jobs API** for state (`queued → running → SUCCESS/FAILURE`)
   and, on success, loads the mesh into the viewport.

> **Verifying "done" for real:** a `200` from the jobs API is not the same as a
> finished asset. Check the job's `state` field, the worker log, and the actual mesh
> bytes — not just the HTTP status.

## Mesh pipeline

Each project stores two meshes:

- **`mesh.glb`** — the canonical, full-resolution asset (used for export and baking).
- **`mesh_view.glb`** — a lightweight copy the browser viewport streams for smooth
  interaction. The gateway generates it lazily/asynchronously.

Editing operations (region painting, re-texturing, decal placement) operate on UV
coordinates and, where relevant, bake results back into the texture so they become a
permanent part of the surface.

## Engines

Engines are model families exposed as independent workers. Requests are routed to a
queue by engine `family` (queue name `<family>-gpu<GPU_ID>`), so you can enable only
the ones your GPU can host. A worker loads exactly one family and drains its queue.

| Engine (id)            | Family        | Input / mode            | ~VRAM  | Gated | License / commercial |
|------------------------|---------------|-------------------------|--------|-------|----------------------|
| `trellis-text`         | trellis       | text → 3D               | ~10 GB | no    | MIT · commercial OK  |
| `trellis-image`        | trellis       | image / multi-view → 3D | ~12 GB | no    | MIT · commercial OK (genuine multi-view) |
| `hunyuan-image`        | hunyuan       | image → 3D (shape)      | ~8 GB  | terms | Tencent Community · non-commercial-ish |
| `hunyuan-textured`     | hunyuan       | image → 3D + PBR        | ~22 GB | terms | Tencent Community · non-commercial-ish |
| `hunyuan-mv`           | hunyuan       | multi-view → 3D         | ~10 GB | no    | Tencent Community · non-commercial-ish |
| `triposr`              | triposr       | single photo → 3D       | ~6 GB  | no    | MIT · commercial OK  |
| `sf3d-image`           | sf3d          | single photo → 3D + PBR | ~7 GB  | ✓     | Stability Community · <$1M + register |
| `hi3dgen-image`        | hi3dgen       | image / multi-view → 3D | ~14 GB | no    | MIT · commercial OK  |
| `partcrafter-image`    | partcrafter   | single photo, part-aware| ~12 GB | no*   | MIT code · pulls NC RMBG-1.4 |
| `sam3d-image`          | sam3d         | real-photo → 3D + tex   | ~24 GB | ✓     | Meta SAM License · conditional |
| `intex-retexture`      | intex         | retexture / region      | ~8 GB  | no    | InTeX no-license · SD1.5 OpenRAIL-M |
| `flux-motif`           | flux          | 2D motif → decal / bake | ~16 GB | ✓     | FLUX.1-dev · **non-commercial** |
| `worldtracing-image`   | worldtracing  | image → 3D              | ~12 GB | ✓     | CC BY-NC-ND · **non-commercial, no-derivatives** |
| `meshflow-refine`      | meshflow      | remesh / clean topology | ~10 GB | ✓     | Meta FAIR NC · **non-commercial** |
| `meshflow-guided`      | meshflow      | image-guided remesh     | ~12 GB | ✓✓    | FAIR NC + DINOv3 (double-gated) |
| `videomdm-motion`      | videomdm      | text → motion           | ~6 GB  | no*   | MIT code · SMPL/SMPL-X deps gated/NC |
| `clothsim-drape`       | clothsim      | drape mesh on mannequin | 0 (CPU)| no    | GPL-3.0 Blender (subprocess) · app stays MIT |
| `flex4dhuman-4d`       | flex4dhuman   | (placeholder)           | —      | —     | no code/weights released — `available=False` |

`clothsim-drape` is the one CPU-only engine: it binds the fixed `clothsim-cpu`
queue (not `<family>-gpu<GPU_ID>`) and calls Blender headless as a subprocess, so it
does not participate in the single-GPU contract.

`*` code/base weights are ungated, but the full feature pulls a gated/non-commercial
dependency (PartCrafter → RMBG-1.4; VideoMDM → SMPL/SMPL-X). Full per-component terms
and the **code-license ≠ weight-license** distinction are in
[`../docs/LICENSES.md`](LICENSES.md).

Some model weights are **gated on Hugging Face** and will fail to download until you
accept their license — a gated weight surfaces as a job `FAILURE` during model load,
not a crash at startup.

### GPU selection

There is a **single source of truth** for which GPU work runs on: the `DEFAULT_GPU`
environment variable (code default `0`). It flows through in one place:

- The gateway takes `gpu` from the request; if absent it uses `settings.default_gpu`.
- The queue suffix is always derived as `f"{family}-gpu{gpu}"`.
- `infra/scripts/engine.sh run <engine> [GPU]` (GPU defaults to `DEFAULT_GPU`) exports
  `CUDA_VISIBLE_DEVICES=<GPU>` and binds queue `<family>-gpu<GPU>`.

So a **single-GPU** machine runs everything on device `0` with no config. On a
multi-GPU machine, set `DEFAULT_GPU=<index>` in `.env` to send generation to another
card (e.g. to keep the display GPU free) — a config choice, never a code default.
`visible_gpus` (empty → auto-detect device count) bounds which GPU indices are valid.

### Per-worker environments

Each engine worker runs in its **own isolated Python venv**. This is not optional:
the pinned stacks are mutually incompatible (e.g. SF3D wants torch 2.4/cu121,
PartCrafter torch 2.5.1/cu124, meshflow torch 2.7.1/cu128, Hi3DGen diffusers 0.30,
FLUX diffusers 0.31). They cannot coexist in one interpreter.

Each engine is described by one file, `infra/engines/<engine>.sh`: upstream repo +
pinned commit, env kind (uv venv or conda), Python and torch index, worker module,
and optional build / weights / runtime-env hooks. `infra/scripts/engine.sh install`
clones the upstream repo into `engines/<dir>`, applies `infra/engines/patches/`,
installs the frozen package set from `infra/engines/locks/`, builds CUDA extensions
for the detected GPU architecture and fetches weights. `engine.sh run` starts the
Celery worker inside that env. On a single GPU the workers still isolate by
environment and serialize on the device.

### Adding an engine

1. Write the worker under `backend/workers/<engine>/src/` (Celery app + engine class).
2. Register the engine + queue routing in `common/engines/registry.py` so jobs for
   that `family` land on `<family>-gpu<N>`.
3. Add `infra/engines/<engine>.sh` (see the existing ones) and verify with
   `engine.sh install <engine> && engine.sh check <engine>`. `start-linux.sh` picks
   it up automatically once installed.

## Frontend notes

- The viewport is built on `@react-three/fiber` + `drei`; decals use drei's `<Decal>`.
- UI strings go through a small dependency-free i18n layer (`src/i18n`) with TR/EN
  dictionaries kept in key-parity. See [`../CONTRIBUTING.md`](../CONTRIBUTING.md).
- The dev server binds `0.0.0.0` and proxies `/api` to the gateway, so remote
  browsers on the LAN only need `FRONTEND_PORT` (3000) open.
- `AUTO_LOGIN=true` (opt-in) serves the token to browsers on the same machine only,
  skipping the login screen there.

## Data & configuration

Runtime paths and secrets come from environment variables (see `.env.example`):
`DATABASE_URL`, `REDIS_URL`, `PROJECTS_DIR`, `TEMPLATES_DIR`, `UPLOADS_DIR`, the
`APP_TOKEN` used for bearer auth, `DEFAULT_GPU` (see [GPU selection](#gpu-selection)),
and `HF_TOKEN` for gated model downloads. Path defaults are repo-relative, so a fresh
clone works without editing absolute paths.

The gateway opens SQLite with `PRAGMA journal_mode=WAL` + `busy_timeout` so the many
worker processes writing back mesh paths don't hit "database is locked". Keep the DB
on a local filesystem. See [`../SECURITY.md`](../SECURITY.md) for hardening notes.
