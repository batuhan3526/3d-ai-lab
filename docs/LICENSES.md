# Model & Engine Licenses

> **The MIT license in [`LICENSE`](../LICENSE) covers the 3D AI Lab application
> code only.** Every generation engine this project integrates ships its own model
> code and/or weights under its own terms. Several are **non-commercial**,
> **gated**, or **no-derivatives** — these restrictions are NOT waived by our MIT
> code license. **Read the relevant row before you download weights, redistribute
> anything, or use an engine commercially.**

**KEY DISTINCTION — code license ≠ weight license.** A repo can be MIT while its
weights are gated or non-commercial. The "weight distribution" column is what
governs redistribution of the checkpoints.

## Summary by commercial-use status

- **Commercial OK (MIT):** TRELLIS, TRELLIS.2-4B, Pixal3D, TripoSR, Hi3DGen, PartCrafter
  *(code)*, VideoMDM *(code)*.
- **Commercial with conditions / bespoke source-available:** Hunyuan3D-2.1
  (Tencent Community, region + 1M-MAU limits), SF3D (Stability Community, <$1M/yr +
  register), SAM3D-Objects (Meta SAM License, ITAR/no-military conditions), SD1.5
  (OpenRAIL-M use-restrictions).
- **Commercial with attribution:** Hi3D v1.0 (Hi3D Open License 1.0 — show "Powered by
  Hi3D 1.0" linking to hi3d.ai in the product; separate licence above 200k MAU or
  USD 1M monthly revenue).
- **NON-COMMERCIAL — do not use in a commercial product:** FLUX.1-dev, FLUX.2-klein-base-9B
  (UltraTex), meshflow,
  world-tracing, mip-splatting, briaai/RMBG-1.4, SMPL/SMPL-X.
- **Gated (accept license + token before download):** SF3D, FLUX.1-dev, FLUX.2-klein-base-9B, meshflow,
  DINOv3, world-tracing weights, SAM3D, SMPL-X, briaai/RMBG-1.4, Hunyuan (accept
  terms).
- **No license / exclude from redistribution:** InTeX source, Flex4DHuman.

## Full component table (22 components)

| Component | License | Commercial | Weight distribution | Gated | OSS strategy |
|---|---|---|---|---|---|
| **TRELLIS** (microsoft/TRELLIS-image-large, TRELLIS-text-*) | MIT | yes | allowed | no | Code + weights both MIT; HF repos public. Clone/download at setup; retain MIT notice. |
| **TRELLIS.2** (microsoft/TRELLIS.2-4B) | MIT | yes | allowed | no (weights) | 4B ckpt MIT + ungated, but the textured pipeline loads GATED DINOv3 at runtime. |
| **Hunyuan3D-2.1** (tencent/Hunyuan3D-2.1) | Tencent Hunyuan 3D 2.1 Community | restricted: free only inside "Territory" (excludes EU/UK/South Korea); >1M MAU needs a separate Tencent license | allowed | accept terms | Bespoke source-available, NOT OSI open-source — do not advertise as "open source". Propagate the license. |
| **TripoSR** (stabilityai/TripoSR) | MIT | yes | allowed | no | Cleanest: MIT covers code + weights, ungated. Retain notice ("Tripo AI & Stability AI"). |
| **SF3D / Stable-Fast-3D** (stabilityai/stable-fast-3d) | Stability AI Community License | restricted: commercial free only if <USD $1M/yr AND registered with Stability | allowed | **GATED** | Source-available, not OSI. Weights gated — request access + `huggingface-cli login`. |
| **Hi3DGen / Stable3DGen** (Stable-X) | MIT | yes | allowed | no | MIT for model + code, engineered for commercial use (NVIDIA-licensed deps removed). Retain notice (Yuchen Lin). |
| **PartCrafter** (wgsxm/PartCrafter) | MIT (code) | restricted: code MIT, but default pipeline auto-pulls briaai/RMBG-1.4 (NON-COMMERCIAL) | unknown (weights) | no (code) | Code MIT; weight-repo license unconfirmed. Swap RMBG for a commercial matte, or treat as non-commercial. |
| **Stable Diffusion v1.5** (runwayml/stable-diffusion-v1-5, via InTeX) | CreativeML OpenRAIL-M | restricted: commercial allowed but subject to OpenRAIL-M Attachment A use-restrictions | allowed | no | Use-restricted, not non-commercial. Must propagate license + Attachment A downstream. |
| **SAM3D-Objects** (Meta) | SAM License (Meta custom) | allowed with conditions (no NC clause; but ITAR/trade-control + no-military + no-reverse-engineering; NOT OSI) | permitted only if full Agreement shipped + recipients bound | ✓ | Ship the SAM License text; do NOT vendor weights (Meta distributes acceptance-gated). |
| **InTeX** | **None / unspecified** (no LICENSE in repo) | undetermined (all-rights-reserved by author) | N/A — ships no weights | — | **Do NOT vendor/redistribute InTeX source.** Depend on it via upstream clone (github.com/ashawkey/InTeX) at setup, or replace it. |
| **meshflow** (facebook/meshflow) | FAIR Noncommercial Research License v1 (Meta) | **prohibited** (non-commercial research only) | non-commercial only, same license + Agreement to recipients | ✓ | Mark engine non-commercial; do NOT vendor weights. User accepts FAIR NC + downloads. |
| **world-tracing** (haoz19/*) | CC BY-NC-ND 4.0 | **prohibited** (non-commercial research only) | verbatim non-commercial redistribution WITH attribution; **NoDerivatives** forbids modified/fine-tuned weights | ✓ | Mark non-commercial; MUST NOT ship modified/derivative weights. Attribution required. |
| **VideoMDM** (code © Guy Tevet; AmirMann/VideoMDM weights) | MIT (code) | code MIT; effective use blocked commercially by deps (SMPL/SMPL-X, AMASS/Fit3D non-commercial) | code redistributable; **must NOT vendor body_models/smpl/*.pkl** | ✓ (deps) | Ship code (retain Guy Tevet notice); user registers/downloads SMPL/SMPL-X + datasets. |
| **Flex4DHuman** | **None** (no LICENSE; code not released) | prohibited/undetermined; only released asset = dataset CC BY-NC-SA 4.0 | N/A — nothing released | — | **EXCLUDE from the public repo.** At most link to the project page/arXiv. |
| **mip-splatting** (SAM3D texture-baking dep) | Gaussian-Splatting License (Inria + MPII) | **prohibited** without explicit written Inria consent | reproduce/distribute only under same license + full notices; diff-gaussian-rasterization + simple-knn submodules inherit it | — | Mark non-commercial; cannot be part of a commercial offering. Include full Inria license if redistributed. |
| **FLUX.1-dev** (black-forest-labs/FLUX.1-dev) | FLUX.1 [dev] Non-Commercial License v1.1.1 (BFL) | **prohibited** (non-commercial only; production needs a paid BFL license). Note: generated *Outputs* may be used commercially, the model may not power a commercial service | non-commercial only, ship License + BFL Attribution Notice; derivatives allowed non-commercially with a "modified" statement | ✓ | Do NOT vendor FLUX weights; mark the motif/decal feature non-commercial. User accepts on HF. |
| **BiRefNet** (ZhengPeng7/BiRefNet) | MIT (per upstream — not evidenced in local cache; **audit-gap**) | allowed if MIT (needs upstream confirmation) | allowed under MIT if confirmed; prefer runtime load over vendoring | no | Load from HF via trust_remote_code; verify BiRefNet's HF license before shipping. |
| **DINOv3** (facebook/dinov3-vitl16-pretrain-lvd1689m) | DINOv3 License (Meta, gated) — exact terms not in local docs (**audit-gap**) | unknown from local sources — review Meta's DINOv3 License directly | controlled by Meta; per-user approval; do NOT vendor | ✓ | Mark as gated Meta dependency (used by meshflow-guided + TRELLIS.2 textured). User requests access. |
| **SMPL-X** (MPI-IS) | SMPL-X / SMPL Model License (Max-Planck) | **prohibited** under research license; commercial needs a separate MPI license | **prohibited** — .pkl files MUST NOT be redistributed | ✓ | Do NOT vendor body_models/smpl/*.pkl (strip from history). User registers at smpl-x.is.tue.mpg.de. |
| **TRELLIS.2-4B** (microsoft/TRELLIS.2-4B) | MIT | yes | allowed | no | Permissive — safe to reference/integrate commercially and auto-download; but the textured worker pulls GATED DINOv3. |
| **Pixal3D** (TencentARC/Pixal3D) | MIT | yes | allowed | no (card sets `extra_gated_eu_disallowed`) | Runs on the TRELLIS.2 stack; loads GATED DINOv3 (official repo, not the upstream mirror) and MoGe-2 (MIT) for the camera. Background removal: open BiRefNet (MIT) instead of the gated, non-commercial briaai/RMBG-2.0. |
| **UltraTex** (yiboz2001/UltraTex; LoRA + decoder Yibo-Zhang/UltraTex on ModelScope) | MIT (code) | code yes; base model no | LoRA/decoder downloaded from ModelScope, not vendored | via FLUX.2-klein | Image-guided retexturing (`ultratex-retexture`). Runs on **FLUX.2-klein-base-9B** (Black Forest Labs, FLUX Non-Commercial License, gated on Hugging Face → **non-commercial**), **Qwen3-8B** text encoder (Apache-2.0) and the FLUX.2 VAE (Comfy-Org copy of the BFL VAE). |
| **Hi3D v1.0** (hi3d-official/Hi3Dv1.0, Sparc3D-based; © OCEANO HK HOLDING LIMITED) | Hi3D Open License Agreement 1.0 (code + weights) | **yes, with conditions**: "Powered by Hi3D 1.0" + link to hi3d.ai in the UI/About page; separate written licence once a product using it exceeds 200,000 MAU or USD 1M monthly revenue; Acceptable Use Policy (Schedule 1) | allowed with the full licence text + NOTICE; generated meshes are free of these conditions | no | Image-guided geometry refinement (`hi3d-refine`). Weights downloaded at install, never bundled. Conditioning encoders DINOv2-large (Apache-2.0) and CLIP ViT-L/14 (MIT). The app shows the required link under **Design → Add shape detail (Hi3D)**. |
| **Base mannequins** (in-house, generated with TRELLIS) | CC0 1.0 (public domain) | yes (no restrictions) | allowed (public domain) | no | Four A/T-pose body GLBs for the mannequin overlay, dressing and 3D sewing. Shipped in `data/templates/mannequins/` (~5 MB). Custom mannequins built from user measurements are generated at runtime and never committed. |
| **passlib** (PyPI) | BSD-3-Clause | yes | allowed | no | Gateway auth password hashing (BATCH-B). |
| **bcrypt** (PyPI, `<4.1` pin) | Apache-2.0 | yes | allowed | no | passlib bcrypt backend; 4.1+ passlib 1.7.4 ile uyumsuz — pin zorunlu. |
| **opennsfw2** (PyPI, OPSİYONEL) | MIT (model: Yahoo open_nsfw BSD-2) | yes | allowed | no | SAFETY_FILTER için lazy/opsiyonel; kurulmazsa filtre "unavailable" olur, hiçbir şey kırılmaz. |
| **Blender** (system binary, OPSİYONEL — clothsim-drape) | GPL-3.0-or-later | yes (ayrı binary; subprocess ile çağrılır, uygulama koduyla LINKLENMEZ → app MIT kalır) | binary VENDOR EDİLMEZ; kullanıcı `apt install blender` veya blender.org'dan kurar | no | Offline kumaş simülasyonu (CPU-only clothsim-cpu worker). GPL Blender ayrı bir process olarak çalışır; GPL uygulama koduna bulaşmaz. Yoksa `clothsim.drape` FAILURE("blender-missing") verir. |
| **QR generator** (vendored — `frontend/src/lib/qr.ts`, Project Nayuki) | MIT | yes | allowed (vendored tek dosya; npm bağımlılığı YOK) | no | Task E2 AR modalı için bağımlılıksız QR matrisi (Nayuki "QR Code generator library" byte-modu portu). MIT lisans başlığı dosyada korunur; harici paket eklemez. |
| **networkx** (PyPI) | BSD-3-Clause | yes | allowed | no | Task E3 3D baskı hazırlama: `trimesh.fill_holes` delik-döngü tespiti için networkx gerektirir (trimesh'in opsiyonel bağımlılığı). Gateway venv'ine eklendi. |
| **xatlas** (PyPI, `xatlas-python`) | MIT | yes | allowed | no | BATCH-G dikiş kalıbı: mesh UV-unwrap (seam + chart açımı). Chart poligonları gerçek ölçeğe kalibre edilip SVG/PDF kalıba dönüştürülür. Gateway venv'ine eklendi. |
| **scipy** (PyPI) | BSD-3-Clause | yes | allowed | no | T1 view-mesh doku yeniden-bake: `spatial.cKDTree` (view texel dünya-konumu → en-yakın orijinal yüzey örneği) + `ndimage.distance_transform_edt` (boş texel gutter dilation). Decimate/xatlas-reparametrize sonrası orijinal dokuyu yeni UV düzenine yeniden örnekleyerek düşük/orta çözünürlükteki beyaz kılcal çizgi + beyaz üçgen artefaktını giderir. Zaten `trimesh.proximity`'nin zorunlu bağımlılığı; açıkça pinlendi. Gateway venv'ine eklendi. |
| **svglib** (PyPI) | LGPL-3.0 | yes (ayrı kütüphane; subprocess/import ile kullanılır, uygulama MIT kalır) | allowed | no | BATCH-G: SVG kalıbını reportlab Drawing'e çevirir (SVG→PDF karolama). Gateway venv'ine eklendi. |
| **reportlab** (PyPI, açık sürüm) | BSD-3-Clause (reportlab open-source) | yes | allowed | no | BATCH-G: dikiş kalıbı SVG'ini A4 karolara bölerek PDF üretir (hizalama artıları + etiket). Gateway venv'ine eklendi. |
| **spandrel** (PyPI) | MIT | yes | allowed | no | Task C Real-ESRGAN doku netleştirme: ESRGAN ağırlığını mimarisiz yükleyen çıkarım kütüphanesi (`texture.upscale`). flux_motif worker venv'ine eklendi (requirements.txt). Kod MIT — güvenli. |
| **Real-ESRGAN weight** (xinntao/Real-ESRGAN, RealESRGAN_x4plus.pth) | BSD-3-Clause | yes | allowed | no | Task C doku upscale ağırlığı (x4). VENDOR EDİLMEZ; `ESRGAN_WEIGHT` env ya da `models/esrgan/RealESRGAN_x4plus.pth`. Yoksa/spandrel yoksa `texture.upscale` FAILURE("esrgan-missing") verir. BSD-3 notice korunur. |

## Redistribution checklist before publishing / shipping weights

1. **Never commit or vendor** SMPL/SMPL-X `.pkl`, FLUX/meshflow/world-tracing/SF3D/
   SAM3D/DINOv3 weights, or InTeX source. Users download them themselves.
2. **Ship the license text** for any bundled model code you do include
   (see [`THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md) / [`NOTICE`](../NOTICE)).
3. **Do not badge non-commercial engines as "recommended"** in the UI, and gate
   commercial deployments away from them.
4. When in doubt, **link to the upstream repo** and let the user accept terms and
   fetch weights via [`infra/scripts/download_models.sh`](../infra/scripts/download_models.sh).
