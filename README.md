# 3D AI Lab

A self-hosted, AI-powered **3D clothing design studio**. Turn a photo or a text
prompt into a textured 3D model, dress it on a mannequin, paint, re-texture, decal,
restyle and export it in a real-time browser viewport — and draft **real sewing
patterns** from body measurements. Everything runs locally on your own Linux machine
and GPU; nothing is sent to the cloud unless you enable a cloud engine.

The UI is **bilingual — English 🇬🇧 / Turkish 🇹🇷**, switchable from the bottom-left
toggle.

---

## Contents

- [What you need](#what-you-need)
- [Quickstart](#quickstart)
- [GPUs: one or many](#gpus-one-or-many)
- [Installing engines](#installing-engines)
- [Features](#features)
- [Engines & licenses](#engines--licenses)
- [Architecture overview](#architecture-overview)
- [API overview](#api-overview)
- [Known limits](#known-limits)
- [Contributing](#contributing)
- [License](#license)

---

## What you need

- **Linux** (any modern x86-64 distro; WSL2 also works) — nothing else is assumed.
- **An NVIDIA GPU + driver** for the local 3D engines. **One GPU is enough**; 24 GB
  runs every engine (one at a time), 8–12 GB runs the lighter ones (TripoSR, InTeX,
  TRELLIS text). Without a GPU you still get the Atelier, cloud engines, export and
  the editor.
- **Tools:** `git`, `curl`, [`uv`](https://github.com/astral-sh/uv), Node 18+ with
  [`pnpm`](https://pnpm.io/), and **Redis** (`sudo apt install redis-server`) or Docker.
- **To build some engines:** the CUDA toolkit (`nvcc`) for engines that compile CUDA
  extensions (TRELLIS, Hi3DGen, InTeX, SF3D, TripoSR, Hunyuan). Conda-based engines
  bring their own toolkit.
- **Disk:** the app is small; **model weights are large** — budget 10–30 GB per
  engine you install.

---

## Quickstart

```bash
git clone <this repo> 3d-ai-lab && cd 3d-ai-lab

# 1. Core: Python env, FreeSewing, frontend, .env with a random APP_TOKEN
bash infra/scripts/setup-linux.sh

# 2. Optional: Blender for dressing / cloth drape / 3D sewing (CPU, ~400 MB)
infra/scripts/engine.sh install clothsim

# 3. One or more GPU engines (each gets its own isolated env)
infra/scripts/engine.sh install triposr      # fastest photo → 3D, ~6 GB VRAM
infra/scripts/engine.sh install trellis      # text/photo → 3D, ~10–12 GB VRAM

# 4. Start everything (Redis, gateway, frontend, installed workers)
bash infra/scripts/start-linux.sh            # → http://localhost:3000
bash infra/scripts/stop-linux.sh             # stop
```

Log in with the `APP_TOKEN` from `.env` ("Use an access token instead"), or create
a user on first launch. Set `AUTO_LOGIN=true` in `.env` to skip the login screen on
the machine that runs the app (other LAN devices still log in). The app also listens
on your LAN: `http://<this-machine-ip>:3000`.

`make help` lists the same steps as make targets; `make test` runs the backend test
suite (no GPU needed).

---

## GPUs: one or many

GPU selection has **one** source of truth, `DEFAULT_GPU` in `.env` (default `0`).
Every worker is pinned to that card (`CUDA_VISIBLE_DEVICES`) and listens on
`<engine>-gpu<N>`; the gateway sends jobs to the same queue.

- **One GPU:** nothing to configure. Workers load their model only when a job
  arrives; use **Unload models / Clear VRAM** in the dashboard to switch between
  heavy engines on a smaller card.
- **Several GPUs:** set `DEFAULT_GPU` to the card that should do the work (e.g. `1`
  to keep the display GPU free). `VISIBLE_GPUS` (e.g. `0,1`) limits the selectable
  indices; empty means auto-detect.

---

## Installing engines

```bash
infra/scripts/engine.sh list              # engines, install state, queue, gated flag
infra/scripts/engine.sh install <name>    # clone pinned upstream → env → build → weights
infra/scripts/engine.sh check <name>      # import the worker inside its env
infra/scripts/engine.sh run <name> [GPU]  # run one worker in the foreground (debugging)
```

- Each engine lives in `engines/<upstream-repo>/` with its own uv venv (or conda env
  for the few that need a pinned CUDA toolkit). Change the location with
  `ENGINES_DIR` in `.env`.
- Upstream repos are cloned at a **pinned commit**; local fixes are applied from
  `infra/engines/patches/`, and Python packages are installed from a frozen,
  known-good set in `infra/engines/locks/`.
- CUDA extensions are compiled for **your** GPU (architecture auto-detected via
  `nvidia-smi`; override with `TORCH_CUDA_ARCH_LIST`).
- **Gated** engines (FLUX, SF3D, Hunyuan, SAM 3D, MeshFlow, World Tracing) need the
  license accepted on Hugging Face and `HF_TOKEN` in `.env`; then
  `engine.sh weights <name>`.
- `start-linux.sh` starts every installed engine (`ENABLED_ENGINES=auto`) or only
  the ones you list.
- Optional pre-download of runtime weights into the Hugging Face cache:
  `bash infra/scripts/download_models.sh` (prints an inventory with sizes/licenses).

---

## Features

Everything below is implemented in this repo. Some engines are **gated** or
**disabled by default** (they need a license you must accept — see
[Engines & licenses](#engines--licenses)); those are marked _(gated)_.

### Generate a 3D model

- **Text → 3D** — describe an object, get a textured mesh (**TRELLIS**).
- **Single photo → 3D** — one image in, textured mesh out. Engines with different
  speed/quality/VRAM trade-offs: **TRELLIS**, **TripoSR** (fastest, ~4 s),
  **SF3D** _(gated)_, **Hi3DGen** (high geometry detail), **PartCrafter**
  (part-aware split), **SAM3D** _(gated)_.
- **Multi-photo → 3D** — feed several angles (front / back / side) of the same
  object for a more consistent result (**TRELLIS**, **Hi3DGen**;
  **Hunyuan multi-view** _(gated)_).
- Each engine exposes **fast / balanced / quality** presets plus advanced
  parameters (steps, CFG, seed, texture size, …) surfaced in the UI.

### Texture & paint

- **Full re-texture** — regenerate the whole surface from a prompt (**InTeX**).
- **Region brush re-texture** — brush a region on the model and regenerate just
  that area.
- **FLUX motif decals** _(gated)_ — generate a 2D motif from a prompt, matte it
  (**BiRefNet**), and place it on the surface as a decal.
- **Decal editing** — upload a logo/pattern, then move / scale / rotate / recolor
  / layer / duplicate it, adjust transparency, and **bake it into the texture**
  with seamless **tiling**.
- **Style transfer** — drive texture generation from a reference image.
- **PBR channel painting** — paint roughness / metallic channels; PBR material
  presets and environment lighting.
- **Texture upscale 4×** — sharpen the base-color texture with **Real-ESRGAN**.

### Iterate & organize

- **Variations gallery** — generate an N-seed batch and pick the best; seeds are
  reproducible.
- **Versions** — automatic + manual snapshots, side-by-side **compare**,
  **undo/redo**, and project **duplication**.
- **Prompt / seed template library** — save and reuse prompts, seeds, and motifs.
- **Photo background removal** — matte an uploaded photo before generation
  (**BiRefNet**).

### Mannequins & cloth (experimental)

- **Base mannequins** — 4 in-house CC0 base meshes, with **auto-fit** and a
  **preview cloth-physics** overlay in the viewport.
- **Blender cloth drape** — physically settle a garment mesh onto a mannequin with
  headless **Blender** (CPU-only). Backend API only — **the UI is hidden and this
  is experimental** (see [Roadmap & known limits](#roadmap--known-limits)).

### Mesh tools & export

- **Retopology** — clean quad/tri remesh via **Instant Meshes** (targets a face
  count).
- **3D-print prep** — hole-fill, **watertight** check + repair, scale-to-height,
  and an **STL** with a report (`watertight_before/after`, holes filled, dims,
  volume).
- **Viewer resolution control** — stream the mesh at anything from ~1k to ~1M
  faces for smooth interaction on any machine.
- **Multi-format export:**
  - **GLB** — viewer copy (with decals) and the original full-resolution asset.
  - **OBJ** — packaged as a ZIP (`.obj` + `.mtl` + texture PNGs).
  - **FBX** — via the Blender bridge (needs Blender installed).
  - **STL** — the 3D-print-prep output (watertight-repaired).
  - **USDZ** — for AR.
  - **Sewing pattern SVG / PDF** _(experimental)_ — UV-unwrap to a scale-calibrated
    1:1 SVG and an A4-tiled PDF.
- **Turntable video** — record a turntable in the browser and convert `webm → mp4`
  (ffmpeg).
- **AR view** — scan a **QR code**: iOS opens **Quick Look** (USDZ), Android opens
  **Scene Viewer** (GLB).

### Home / ops

- **Multi-user home auth** — first-run setup screen creates the first user;
  additional users share a common gallery. A machine `APP_TOKEN` also works for
  scripts/workers.
- **Job queue panel** — live view of queued / running / done / failed jobs.
- **Live system & scene metrics** — per-GPU utilization + VRAM, CPU / RAM / disk,
  and scene FPS / triangle count, with **one-click VRAM release** (unload idle
  engines).
- **TR / EN UI** — a small dependency-free i18n layer; add a locale by copying one
  dictionary file.

### Atelier — real sewing patterns (no GPU)

- **Pattern from measurements** — pick one of 11 FreeSewing designs (t-shirt, tank,
  sweatshirt, hoodie, shirt, bodice block, pencil skirt, circle skirt, trousers,
  leggings, wrap pants), enter 5 body measurements (the other ~40 are estimated and
  editable) and download a **print-ready A4 PDF / true-scale SVG** with the cut list.
- **Fabric layout (nesting)** — lays the pieces on your fabric width with minimal
  waste and tells you how much fabric to buy.
- **3D sewing** — sews the pattern onto a mannequin in Blender with 8 fabric presets
  (t-shirt, pencil skirt, circle skirt), then opens it in the designer.
- **Mannequin from your measurements** — builds a body that matches you for fittings.

### Dressing & tailor measurements

- **Dress after generation** — a generated garment is fitted onto the chosen
  mannequin automatically, with a size-ratio guard that rejects non-garments.
- **Tailor measurements** — chest / waist / hip / hem / cuff circumference of the
  dressed garment in cm.

### Cloud engines (optional, paid)

- Tripo, Meshy, Rodin, fal, Stability, Replicate, OpenAI, Gemini, BFL, Ideogram,
  Recraft — enabled per provider by putting its key in `.env`; no GPU needed.
  See [`docs/CLOUD_API_REFERENCE.md`](docs/CLOUD_API_REFERENCE.md).

---

## Engines & licenses

Weights are **not bundled** — they download at setup/runtime. Several engines are
**gated** (accept the license on Hugging Face and set an `HF_TOKEN` first) and
several are **non-commercial**. A gated weight surfaces as a job **`FAILURE`**
during model load, not a crash at startup.

- **Set `HF_TOKEN=` in `.env`** (from
  [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)) before
  fetching gated repos. Gated / non-commercial examples: **FLUX.1-dev**,
  **DINOv3**, **SMPL-X**, **SF3D**, **SAM3D**, **meshflow**, **world-tracing**,
  **Hunyuan** (accept terms).

> ⚠️ **Code license ≠ weight license.** Our MIT app license does **not** cover the
> models. Some engines are non-commercial (FLUX.1-dev, meshflow, world-tracing,
> SMPL/SMPL-X, RMBG-1.4), some are source-available with commercial conditions
> (Hunyuan3D, SF3D, SAM3D). **Do not assume the MIT badge lets you use every engine
> commercially.**

| Engine (id) | Input / mode | ~VRAM | Gated | Commercial |
|---|---|---|---|---|
| `trellis-text` | text → 3D | ~10 GB | no | MIT · OK |
| `trellis-image` | image / multi-view → 3D | ~12 GB | no | MIT · OK |
| `triposr` | single photo → 3D (fast) | ~6 GB | no | MIT · OK |
| `hi3dgen-image` | image / multi-view → 3D | ~14 GB | no | MIT · OK |
| `partcrafter-image` | single photo, part-aware | ~12 GB | no* | MIT code · pulls NC matte |
| `sf3d-image` | single photo → 3D + PBR | ~7 GB | ✓ | Stability Community · <$1M + register |
| `hunyuan-image` | image → 3D (shape) | ~8 GB | terms | Tencent Community · non-commercial-ish |
| `hunyuan-textured` | image → 3D + PBR | ~22 GB | terms | Tencent Community · non-commercial-ish |
| `hunyuan-mv` | multi-view → 3D | ~10 GB | terms | Tencent Community · non-commercial-ish |
| `sam3d-image` | real-photo → 3D + tex | ~24 GB | ✓ | Meta SAM License · conditional |
| `intex-retexture` | re-texture / region brush | ~8 GB | no | InTeX (no license) · SD1.5 OpenRAIL-M |
| `flux-motif` | 2D motif → decal / bake | ~16 GB | ✓ | FLUX.1-dev · **non-commercial** |
| `worldtracing-image` | image → 3D | ~12 GB | ✓ | CC BY-NC-ND · **non-commercial** |
| `meshflow-refine` | remesh / clean topology | ~10 GB | ✓ | FAIR NC · **non-commercial** |
| `meshflow-guided` | image-guided remesh | ~12 GB | ✓✓ | FAIR NC + DINOv3 (double-gated) |
| `videomdm-motion` | text → motion | ~6 GB | no* | MIT code · SMPL/SMPL-X deps gated/NC |
| `clothsim-drape` | drape mesh on mannequin | 0 (CPU) | no | GPL Blender (subprocess) · app stays MIT |
| `flex4dhuman-4d` | (placeholder) | — | — | no code/weights released |

`*` the code/base weights are ungated, but the full feature pulls a
gated/non-commercial dependency (PartCrafter → RMBG-1.4; VideoMDM → SMPL/SMPL-X).

**Read [`docs/LICENSES.md`](docs/LICENSES.md) before you download or ship
anything** — it has the full per-component table, the code-vs-weights distinction,
and a redistribution checklist. Attribution / redistribution obligations are in
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) and [`NOTICE`](NOTICE);
content-safety and responsible-use notes (no NSFW filter is active by default) are
in [`SECURITY.md`](SECURITY.md).

---

## Architecture overview

```
Browser (React + three.js)  ── /api proxy ──►  FastAPI Gateway (:9000)
                                                   │  projects, auth, dispatch
                                        Redis  ◄───┤  enqueue jobs (Celery)
                                                   ▼
                            GPU workers  (one Celery queue per engine)
                              TRELLIS · Hunyuan · Hi3DGen · TripoSR · SF3D ·
                              PartCrafter · SAM3D · InTeX · FLUX · MeshFlow · …
                                                   ▼
                       data/  →  projects, uploads, meshes, thumbnails
```

- The **gateway** exposes the REST API, manages projects/auth, and dispatches jobs
  onto per-engine Redis/Celery queues.
- Each **worker** loads one model family and drains its queue on the GPU.
- Meshes are stored as a canonical full-resolution `mesh.glb` plus a lightweight
  `mesh_view.glb` the viewer streams.
- SQLite runs in WAL mode so many worker processes can write back mesh paths without
  locking.

Full details — request lifecycle, mesh pipeline, GPU selection, per-worker
environments, and how to add an engine — are in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## API overview

The gateway is a FastAPI app; interactive **OpenAPI docs** are served at
**`http://localhost:9000/docs`** (and the raw schema at `/openapi.json`). Health
is at `/health`. Broad route groups: `auth`, `projects`, `generate`, `variations`,
`versions`, `jobs`, `engines`, `templates`, `prompt_library`, `system`, `drape`,
`retopo`, `upscale`, `sewing`, `print_prep`, `export3d`, `ar`, `media`, and a
websocket (`ws`) for live job updates. Most write endpoints require a bearer token
(session or `APP_TOKEN`); public read endpoints serve meshes, thumbnails, and AR
assets so phones can fetch them without an auth header.

---

## Known limits

- **Hobby-grade, not a hardened service.** Auth is designed for a home/LAN with a
  shared gallery — not multi-tenant isolation. Don't expose it to the internet
  without a reverse proxy, TLS and rate limiting (see [`SECURITY.md`](SECURITY.md)).
- **Text → 3D struggles with complex garments.** For detailed pieces, generate a
  product photo with FLUX first ("ghost mannequin", no visible body) and use
  photo → 3D.
- **3D sewing** covers the t-shirt, pencil skirt and circle skirt patterns; other
  patterns are 2D (PDF/SVG) only.
- **Sewing pattern from a 3D mesh** (UV unwrap) is experimental — use the Atelier
  patterns for anything you will actually cut.
- **Several engines are gated / non-commercial** and stay locked until you accept
  their licenses and download weights.
- `flex4dhuman-4d` and `pixworld-scene` are placeholders (no upstream release yet).

---

## Contributing

Issues and PRs welcome — new engines, languages, export formats, and UI polish
especially. See [`CONTRIBUTING.md`](CONTRIBUTING.md).

## License

The **application code** is [MIT](LICENSE) © 2026 Batuhan Bayraktar.

> ⚠️ **The MIT license covers the app code only — NOT the models.** The engines
> this project integrates keep their own licenses; several are **non-commercial**,
> some are **gated**, and some are **source-available with commercial conditions**.
> Per-engine terms and the code-vs-weights distinction are in
> [`docs/LICENSES.md`](docs/LICENSES.md).
