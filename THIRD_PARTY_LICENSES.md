# Third-Party Licenses & Attribution

3D AI Lab integrates a fleet of third-party 3D-generation and image models. The
application code is MIT (see [`LICENSE`](LICENSE)); **the models below keep their
own licenses.** This file records attribution and redistribution obligations. For
the full commercial/gated/weight-distribution matrix see
[`docs/LICENSES.md`](docs/LICENSES.md). Machine-facing short form is in
[`NOTICE`](NOTICE).

> Model **weights are NOT vendored** in this repository. They are downloaded at
> setup/runtime from Hugging Face (or the vendor's site for gated ones) via
> [`infra/scripts/download_models.sh`](infra/scripts/download_models.sh). Each
> user is responsible for accepting the relevant license before download.

## Permissive (MIT / Apache-style) — attribution only

- **TRELLIS** and **TRELLIS.2 / TRELLIS.2-4B** — MIT, © Microsoft. Code + weights
  MIT. https://github.com/microsoft/TRELLIS
- **TripoSR** — MIT, © Tripo AI & Stability AI. Code + weights MIT.
  https://github.com/VAST-AI-Research/TripoSR
- **Hi3DGen / Stable3DGen** — MIT, © Yuchen Lin. Engineered for commercial use.
  https://github.com/Stable-X/Hi3DGen
- **PartCrafter** — MIT (code), © Yuchen Lin. *Weight-repo license unconfirmed;*
  default pipeline pulls the **non-commercial** briaai/RMBG-1.4.
  https://github.com/wgsxm/PartCrafter
- **VideoMDM** — MIT (code), © 2022 Guy Tevet. Retain the notice. Runtime deps
  (SMPL/SMPL-X, AMASS, Fit3D) are separately licensed and non-commercial.
- **BiRefNet** (matting) — MIT per upstream (ZhengPeng7/BiRefNet); loaded at
  runtime via `trust_remote_code`. *Verify the HF license text before shipping.*

- **FreeSewing** (`@freesewing/core`, `@freesewing/models`, design packages
  aaron, bella, hugo, lily, penelope, sandy, simon, sven, teagan, titan, waralee
  and their transitive `@freesewing/*` deps, all v4.10.2) — MIT, © Joost De Cock
  and the FreeSewing contributors. Installed via npm into
  `backend/services/freesewing/node_modules` (not vendored). The body-measurement
  estimator (`backend/common/src/common/body_measurements.py`) ports the base
  table and ratios from `@freesewing/models` `neckstimate.mjs` (MIT).
  https://github.com/freesewing/freesewing

## Source-available / commercial-with-conditions — read before commercial use

- **Hunyuan3D-2.1** — Tencent Hunyuan 3D 2.1 Community License. Free only inside
  the "Territory" (excludes EU / UK / South Korea); >1M MAU requires a separate
  Tencent license. NOT OSI open-source.
- **SF3D / Stable-Fast-3D** — Stability AI Community License. Commercial free only
  under USD $1M/yr revenue **and** Stability registration. Weights **gated**.
- **SAM3D-Objects** — Meta SAM License. Commercial permitted **with conditions**
  (ITAR/trade-control, no-military, no-reverse-engineering); the full Agreement
  must be shipped to recipients. Weights acceptance-gated.
- **Stable Diffusion v1.5** (used by InTeX) — CreativeML OpenRAIL-M. Commercial
  allowed but you MUST propagate the license and its Attachment A use-based
  restrictions downstream.

## Non-commercial — MUST NOT be used in a commercial product

- **FLUX.1-dev** — FLUX.1 [dev] Non-Commercial License v1.1.1, © Black Forest
  Labs. Production/commercial use needs a paid BFL license. Ship the License + the
  BFL Attribution Notice if redistributed. (Generated *outputs* may be used
  commercially; the model may not power a commercial service.)
- **meshflow** — FAIR Noncommercial Research License v1, © Meta. Research only.
- **world-tracing** — CC BY-NC-ND 4.0. Non-commercial **and** no-derivatives:
  do not distribute modified/fine-tuned weights. Attribution required.
- **mip-splatting** (+ diff-gaussian-rasterization, simple-knn; used by the SAM3D
  texture-baking path) — Gaussian-Splatting License (Inria + MPII). Non-commercial
  without explicit written Inria consent.
- **SMPL / SMPL-X** — Max-Planck Model License. Non-commercial research; `.pkl`
  files MUST NOT be redistributed. Register at https://smpl-x.is.tue.mpg.de.
- **briaai/RMBG-1.4** — non-commercial (matting model pulled by PartCrafter).
- **DINOv3** — Meta DINOv3 License, gated. Used by meshflow-guided, the TRELLIS.2
  textured pipeline, `trellis2-image` and `pixal3d-image`. Review Meta's terms; do not
  vendor.
- **Pixal3D** — MIT, © Tencent ARC / Tsinghua. Code + weights (TencentARC/Pixal3D),
  downloaded at install / first run. Uses MoGe-2 (MIT) for camera estimation.
- **UltraTex** — MIT code (yiboz2001/UltraTex), LoRA + decoder from ModelScope
  (Yibo-Zhang/UltraTex). Base model **FLUX.2-klein-base-9B** — FLUX Non-Commercial License
  (Black Forest Labs), gated; text encoder **Qwen3-8B** — Apache-2.0 (Alibaba Qwen). Weights
  are downloaded at install, never bundled.
- **Hi3D v1.0** — Hi3D Open License Agreement 1.0, © 2026 OCEANO HK HOLDING LIMITED
  (hi3d-official/Hi3Dv1.0, code + weights, built on Sparc3D). Commercial use allowed with
  the "Powered by Hi3D 1.0" attribution linking to https://www.hi3d.ai/; a separate licence
  is required above 200,000 MAU or USD 1M monthly revenue. Required notice: "Hi3D is
  licensed under the Hi3D Open License Agreement Version 1.0. Copyright © 2026 OCEANO HK
  HOLDING LIMITED. All rights not expressly granted are reserved. The Hi3D trademarks are
  owned by OCEANO HK HOLDING LIMITED or its applicable affiliate(s)." Weights are
  downloaded at install, never bundled; conditioning encoders DINOv2-large (Apache-2.0)
  and CLIP ViT-L/14 (MIT).
- **BiRefNet** (ZhengPeng7/BiRefNet) — MIT. Background removal for `trellis2-image` and
  `pixal3d-image` (replaces the gated, non-commercial briaai/RMBG-2.0 default).

## No license — excluded from redistribution

- **InTeX** source has **no LICENSE file** (all-rights-reserved by upstream
  author). This repo depends on it via an upstream clone at setup time and does
  **not** vendor it. Do not redistribute InTeX source.
- **Flex4DHuman** — no code/weights released and no license. Excluded; only the
  project page/arXiv may be linked. Its released dataset is CC BY-NC-SA 4.0.

---

Every attempt has been made to represent these terms accurately from the upstream
sources at audit time (2026-07-06). This file is informational, not legal advice —
consult each project's authoritative license before relying on it.
