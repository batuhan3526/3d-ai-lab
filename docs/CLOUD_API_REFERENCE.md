# Cloud Generation API Reference (3D + Image)

Researched 2026-10-17 from vendor docs, for writing Python `requests` clients **without API keys**.
Nothing here was tested against a live endpoint. Anything not confirmed in official docs or official SDK source is marked **UNVERIFIED**.

General rules that hold for every provider:
- Output URLs expire (5 min to 24 h). **Download right away** into our own storage. Never store the vendor URL.
- Back off on 429 using `Retry-After` when it is present, else exponential (1, 2, 4 ... s, capped at about 30 s).
- Never log keys. Read them from env vars only.

---

## 1. Tripo3D (3D: text→3D, image→3D)

> **Important:** the docs now describe **API v3**. Tripo's own migration guide says v2 (`/v2/openapi/task` with a `type` field) "is being shut down" (no date given). **Implement v3.**

| Item | Value |
|---|---|
| Base URL | `https://openapi.tripo3d.com/v3` (the docs say this host serves both regions; consoles are developers.tripo3d.ai and developers.tripo3d.com) |
| Auth | `Authorization: Bearer <key>` (keys look like `tsk_...`/`sk-...`) |
| Env var | `TRIPO_API_KEY` (the vendor's own suggestion) |
| Async | Yes. Create returns `data.task_id`, then poll. Webhooks also exist (`/en/docs/webhooks`, details not reviewed) |

**Upload (needed for local images):** `POST /v3/files`, multipart field `file`. JPEG/PNG up to 20 MB. Models (GLB/GLTF/FBX/OBJ/STL) up to 150 MB; use the large-file endpoint above 60 MB.
Response: `{"code":0,"data":{"file_token":"file_abc123"}}`. **Base64 inputs are rejected on v3** (per the migration guide). Uploads are limited to about 10/min (migration guide, UNVERIFIED).

**Text→3D:** `POST /v3/generation/text-to-model` (JSON)
**Image→3D:** `POST /v3/generation/image-to-model` (JSON)

| Field | t2m | i2m | Notes |
|---|---|---|---|
| `prompt` | req | – | ≤1024 chars |
| `negative_prompt` | opt | – | ≤255 chars |
| `input` | – | req | a `file_token`, a public image URL, or the task_id of a text_to_image task. PNG/JPEG/WebP, ≤20 MB, ≥256 px recommended |
| `model` | **req** | **req** | `v3.1-20260211` (latest), `v3.0-20250812`, `v2.5-20250123`. P-series `P1-20260311` has its own pages. The quickstart's Python sample uses `tripo-v3.1` (inconsistent, so use the dated string) |
| `texture` | true | true | false = bare geometry |
| `pbr` | true | true | adds base_color/metallic/roughness/normal maps; forces texture=true |
| `texture_quality` | `standard` | `standard` | `fast` (needs `texture_version=v3.5-20260815`, else error 1004), `standard`, `detailed`, `extreme` (8K, extra credits) |
| `geometry_quality` | `standard` | `standard` | `detailed` = Ultra (model ≥ v3.0) |
| `face_limit` | adaptive | adaptive | max 1.5M for v3.1 standard |
| `model_seed`, `texture_seed` | opt | opt | `image_seed` is t2m only |
| `quad` | false | false | **forces FBX output, so avoid it when you want GLB** |
| `auto_size`, `smart_low_poly`, `generate_parts`, `compress:"geometry"`, `export_uv`, `orientation`, `enable_image_autofix` | opt | opt | see docs |

```json
POST /v3/generation/image-to-model
{"input":"file_abc123","model":"v3.1-20260211","texture":true,"pbr":true,"texture_quality":"standard"}
→ {"code":0,"data":{"task_id":"..."}}
```

**Poll:** `GET /v3/tasks/{task_id}` every 1 to 2 s. Set a 5 min cap (the docs suggest one).
- `data.status`: `queued`, `running` (in progress) | `success` | `failed`, `cancelled`, `banned`, `expired` (terminal failures). The migration guide says v3 maps banned/expired to `failed` with codes 2008/2018. **Treat any unknown status as failed.**
- `data.progress` 0–100.
- **Result:** `data.output.model_url` (GLB; `quad` gives FBX), plus `data.output.rendered_image_url` (preview PNG) and `data.credits_consumed`.
- Expiry: the quickstart says model URLs expire after **5 minutes**; the migration guide says about 24 h. Download immediately.

**Errors:** JSON `{"code":int,"message":str,"suggestion":str,"request_id":str}`. HTTP 400/401/403/404/429/500.
Codes: 1000 = invalid key, 1001 = missing auth header, 2010 = insufficient credits (HTTP 403), 2000/1007 = rate limit (HTTP 429). Retry only 429/500 (1, 2, 4 s, at most 5 tries).
**Limits:** per-key RPS is not published (the quickstart says stay ≤1 req/s). Headers: `X-RateLimit-Limit/Remaining/Reset`. Default concurrency for 3D H-series is 10 running tasks.
**Latency:** 10–120 s (quickstart). **Pricing:** credit based. The doc example shows 100 credits for a detailed textured task. Per-task table and USD/credit: **UNVERIFIED** (tripo3d.ai/en/pricing returned 403).
Docs: developers.tripo3d.com/en/docs/{quick-start, generation-text-to-model/standard, generation-image-to-model/standard, files, task-lifecycle, error-handling, rate-limits, migration-v2-to-v3}

*Legacy v2 (only if needed):* `POST https://api.tripo3d.ai/v2/openapi/task` with `{"type":"image_to_model","file":{"type":"png","file_token":"..."},"model_version":"v2.5-20250123"}`. Upload is `POST /v2/openapi/upload` and returns `data.image_token`. Results are in `output.pbr_model`, `output.model` or `output.base_model`. (Host and fields come from the third-party migration guide: UNVERIFIED.)

---

## 2. Meshy (3D: text→3D two-stage, image→3D)

| Item | Value |
|---|---|
| Base URL | `https://api.meshy.ai` |
| Auth | `Authorization: Bearer msy_...` |
| Env var | `MESHY_API_KEY` |
| Async | Yes. Create returns `{"result":"<task_id>"}`, then poll GET (SSE `/stream` also available) |

**Text→3D, stage 1 (preview, mesh only):** `POST /openapi/v2/text-to-3d`
```json
{"mode":"preview","prompt":"a leather jacket","ai_model":"latest","target_formats":["glb"],
 "should_remesh":true,"topology":"triangle","target_polycount":30000}
```
Fields: `prompt` (≤800 chars, req). `ai_model`: `latest` (= meshy-7.1), `meshy-7.1`, `meshy-6`, `meshy-6-lite`; smart topology uses `meshy-t2`/`meshy-t2.5` with `model_type:"smart-topology"`. Also `topology` (`triangle`|`quad`), `should_remesh`, `target_polycount` (100–300k), `pose_mode` (`a-pose`|`t-pose`|`""`), `geometry_resolution` (`standard`|`2k`|`4k`, 7.1 only), `target_formats` (glb, obj, fbx, stl, usdz, 3mf), `moderation`, `auto_size`, `origin_at`. `art_style` is deprecated. **`seed` is not documented.**

**Text→3D, stage 2 (refine, adds texture):** `POST /openapi/v2/text-to-3d`
```json
{"mode":"refine","preview_task_id":"<SUCCEEDED preview id>","enable_pbr":true,
 "texture_prompt":"brown leather","texture_resolution":"2k"}
```
`texture_image_url` (public URL or **base64 data URI**, ≤20 MB) is an alternative to `texture_prompt`. `remove_lighting` defaults to true (meshy-6 only). `texture_resolution`: `2k`|`4k`|`8k`.
Poll: `GET /openapi/v2/text-to-3d/{id}`.

**Image→3D:** `POST /openapi/v1/image-to-3d`
```json
{"image_url":"data:image/png;base64,iVBOR...","ai_model":"latest","should_texture":true,
 "enable_pbr":true,"should_remesh":true,"target_polycount":30000,"target_formats":["glb"]}
```
`image_url` takes a **public URL or a base64 data URI** (jpg/jpeg/png/webp, ≤20 MB), so no upload step is needed. Poll: `GET /openapi/v1/image-to-3d/{id}`.

**Task object:** `status`: `PENDING`, `IN_PROGRESS` | `SUCCEEDED` | `FAILED`, `CANCELED`. Also `progress` 0–100, `task_error.message`, and `consumed_credits` (0 on failure; failed tasks are refunded).
**Result:** `model_urls.glb` (signed URL with `Expires`; formats that were not generated are omitted), plus `thumbnail_url` and `texture_urls[0].base_color|metallic|normal|roughness`.

**Errors:** body `{"message": "..."}`. 400 bad param, 401 bad key, 402 insufficient credits, 404, 409 (delete while IN_PROGRESS), 429.
**Rate limits:** 20 req/s on all paid plans. Queue cap (PENDING+IN_PROGRESS): Pro 10, Studio 20, Premium 30, Ultra 100. A 429 for RPS has `Retry-After`; a 429 for queue-full does not.
**Pricing (credits):** with meshy-7.1/6: preview 20, refine 10 (8K: 15), image→3D mesh-only 20, image→3D textured 30 (8K: 35); meshy-6-lite is about 5/15. Ultra geometry adds 5. USD per credit is not on the docs page (**UNVERIFIED**).
**Latency:** not documented (**UNVERIFIED**; expect minutes for preview+refine).
Docs: docs.meshy.ai/en/api/{text-to-3d, image-to-3d, pricing, rate-limits, authentication}

---

## 3. Hyper3D Rodin (3D: text→3D, image→3D, Gen-2.5)

| Item | Value |
|---|---|
| Base URL | `https://api.hyper3d.com/api/v2`. The legacy `https://hyperhuman.deemos.com/api/v2` is not mentioned in current docs (**UNVERIFIED** whether it still works) |
| Auth | `Authorization: Bearer <key>` |
| Env var | `RODIN_API_KEY` (the name used in the docs' curl examples) |
| Async | Yes, three steps: submit, then status (by subscription_key), then download (by task uuid) |

**Submit:** `POST /rodin`, **multipart/form-data**
```bash
curl --fail-with-body -X POST https://api.hyper3d.com/api/v2/rodin \
  -H "Authorization: Bearer $RODIN_API_KEY" \
  -F images=@input.png -F tier=Gen-2.5-Medium -F mesh_mode=Raw -F quality=medium \
  -F geometry_file_format=glb
```
| Field | Notes |
|---|---|
| `images` | 1–5 files (repeat the field). The first one drives materials. **Omit for text→3D.** Images are uploaded as multipart (no URL/base64) |
| `prompt` | required for text→3D, optional for image→3D |
| `tier` | **always send it**: `Gen-2.5-Extreme-Low`, `-Low`, `-Medium`, `-High`, `-Extreme-High`. If omitted it falls back to Gen-1/1.5 |
| `texture_mode` | `extreme-low`…`extreme-high` (default follows tier) |
| `geometry_file_format` | `glb` is referenced in the docs; other values (usdz/fbx/obj/stl) are **UNVERIFIED** |
| `mesh_mode` | `Raw` in examples (`Quad` is **UNVERIFIED**) |
| `quality` | `medium` in examples (`high`/`low`/`extreme-low` are **UNVERIFIED**) |
| `geometry_instruct_mode` | `creative` (≥Medium) or `faithful` (experimental) |
| `addons` (`HighPack`), `uhd_texture`, `quality_override` | texture resolution and polycount options |
| `material` (PBR/Shaded), `seed`, `TAPose`, `bbox_condition` | **UNVERIFIED** (not in current Gen-2.5 page) |

Response (HTTP **201**): `{"message", "uuid", "jobs":{"uuids":[...], "subscription_key":"..."}, "consumed", "error"}`. Accept it only if `error` is empty and `uuid` is non-empty.

**Status:** `POST /status`, JSON `{"subscription_key":"<jobs.subscription_key>"}` returns `{"jobs":[{"uuid":"...","status":"Done"}]}`.
Status values: `Waiting` (may carry `queue_length`), `Generating` | `Done` | `Failed`. **Success = every job is Done; stop if any job is Failed.** Wait 5 s before the first poll, back off up to 30 s, and honor `Retry-After`.

**Download:** `POST /download`, JSON `{"task_uuid":"<top-level uuid>"}` returns `{"list":[{"name":"model.glb","url":"..."}, ...]}`. Pick the entry whose `name` ends in `.glb`. URLs are short-lived (a third-party page says 10 min, UNVERIFIED).

**Errors:** 400 invalid fields/files, 401 auth, 429 throttled (all three endpoints). Success code is 201.
**Pricing:** 0.5 credits base for Gen-2.5, +0.5 for `Gen-2.5-Extreme-High`, +2.0 for `texture_mode=extreme-high`. USD per credit is **UNVERIFIED**. **Latency:** not documented (**UNVERIFIED**).
Docs: docs.hyper3d.ai/en/api-specification/{rodin-gen2-5, check-status, download-results}

---

## 4. fal.ai (queue API; 3D + image models)

| Item | Value |
|---|---|
| Queue base | `https://queue.fal.run` |
| Auth | `Authorization: Key <FAL_KEY>` (note **`Key`**, not Bearer) |
| Env var | `FAL_KEY` (fal SDK convention) |
| Async | Yes (queue). The sync host `https://fal.run/{model_id}` exists (SDK `run`); the exact URL form is not in the page we read (**UNVERIFIED**). Webhook: append `?fal_webhook=https://...` to the submit URL |

**Submit:** `POST https://queue.fal.run/{model_id}` with the model's input JSON as body.
Response: `{"request_id","status_url","response_url","cancel_url","queue_position"}`.
> **Use the returned `status_url` and `response_url` verbatim.** For multi-segment ids (e.g. `fal-ai/hunyuan3d-v3/image-to-3d`) the official SDK builds them **without the sub-path**: `https://queue.fal.run/fal-ai/hunyuan3d-v3/requests/{id}/status` (verified in fal_client source).

**Status:** `GET {status_url}` (add `?logs=1` for logs). Values: `IN_QUEUE` (has `queue_position`), `IN_PROGRESS` | `COMPLETED` (has `metrics.inference_time`). A failed request is still `COMPLETED` but carries `error` and `error_type`, so check for them. SSE variant: `{status_url}/stream`.
**Result:** `GET {response_url}` returns the model-specific JSON below. Cancel: `PUT {cancel_url}` (202 `CANCELLATION_REQUESTED`, 400 `ALREADY_COMPLETED`).
**Errors:** infrastructure errors have JSON `detail` and `error_type` plus an `X-Fal-Error-Type` header. The validation (422) body shape is **UNVERIFIED** (likely `{"detail":[...]}`).

**File inputs:** every `*_url` field accepts a public URL. **Base64 data URIs are accepted** ("Models also accept base64-encoded data URIs"), but only for small files (a few KB); the docs say they inflate the request.
Upload via REST (from official `fal_client` source; not in prose docs):
1. `POST https://rest.fal.ai/storage/upload/initiate?storage_type=gcs`, headers `Authorization: Key ...`, JSON `{"file_name":"x.png","content_type":"image/png"}`. Response: `{"upload_url":"...","file_url":"..."}`
2. `PUT upload_url` with raw bytes and `Content-Type`, **no auth header**. Then pass `file_url` as the input.

Outputs are CDN URLs (`v3b.fal.media`). Retention is configurable via the `X-Fal-Object-Lifecycle-Preference` header; the default is **UNVERIFIED**.

### fal 3D models
| model_id | Inputs (req **bold**) | GLB output path | Price (model page) |
|---|---|---|---|
| `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d` | **`input_image_url`** (128–5000 px, ≤8 MB, JPG/PNG/WEBP), `back_/left_/right_/top_/bottom_/left_front_/right_front_image_url`, `generate_type` (`Normal`\|`Geometry`), `enable_pbr`, `face_count` (40k–1.5M, def 500k) | `model_glb.url` (also `model_urls.glb.url`, `thumbnail.url`, `seed`) | $0.375; +$0.15 each for PBR, multi-view, custom face_count |
| `fal-ai/hunyuan-3d/v3.1/pro/text-to-3d` | **`prompt`** (≤1024 chars), `generate_type`, `enable_pbr`, `face_count` | `model_glb.url` | $0.375 (+ the same add-ons) |
| `fal-ai/hunyuan-3d/v3.1/rapid/text-to-3d` | **`prompt`** (≤200 chars), `enable_pbr`, `enable_geometry` | **`model_urls.glb.url`** (no top-level glb; main file `model_obj` is OBJ) | $0.225; PBR +$0.15 |
| `fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d` | **`input_image_url`**, `enable_pbr`, `enable_geometry` | `model_urls.glb.url`. **The doc example's `model_glb` holds `model/obj` content, so check `content_type`** | $0.225; PBR +$0.15 |
| `fal-ai/hunyuan3d-v3/image-to-3d` (v3.0) | **`input_image_url`**, back/left/right views, `enable_pbr`, `face_count`, `generate_type` (`Normal`\|`LowPoly`\|`Geometry`), `polygon_type` | `model_glb.url` | $0.375 (Geometry $0.225) |
| `fal-ai/trellis` | **`image_url`**, `seed`, `ss_guidance_strength` 7.5, `ss_sampling_steps` 12, `slat_guidance_strength` 3, `slat_sampling_steps` 12, `mesh_simplify` 0.95, `texture_size` 512/1024/2048 | `model_mesh.url` | $0.02 |
| `fal-ai/trellis-2` (exists) | **`image_url`**, `seed`, `resolution` 512/1024/1536 (def 1024; the schema says string but the example sends a number, so test both), `texture_size` 1024/2048/4096 (def 2048), `decimation_target` 500000, `remesh` true, plus many `ss_*`, `shape_slat_*`, `tex_slat_*` knobs | `model_glb.url` | $0.05 per unit (pricing page) |

### fal image models (all return `images[i].url`, plus `content_type`/`width`/`height`; `sync_mode:true` returns a data URI instead)
| model_id | Key inputs (req **bold**) | Price |
|---|---|---|
| `fal-ai/flux-pro/v1.1` | **`prompt`**, `image_size` (`square_hd`,`square`,`portrait_4_3`,`portrait_16_9`,`landscape_4_3`(def),`landscape_16_9` or `{"width":..,"height":..}`), `seed`, `num_images`, `output_format` `jpeg`(def)\|`png`, `safety_tolerance` "1"–"6", `enhance_prompt` | $0.04/MP |
| `fal-ai/flux-2-pro` | **`prompt`**, `image_size` (same enums), `seed`, `safety_tolerance` 1–5, `enable_safety_checker`, `output_format` | $0.03 first MP, +$0.015/extra MP (derived from the page's 1920×1080 = $0.045 example) |
| `fal-ai/flux-pro/kontext` (image **edit**) | **`prompt`**, **`image_url`**, `aspect_ratio`, `seed`, `guidance_scale` 3.5, `output_format`, `safety_tolerance`, `num_images` | $0.04/image |
| `fal-ai/nano-banana` | **`prompt`**, `num_images`, `aspect_ratio` (21:9…9:16, def 1:1), `output_format` `png`(def)/jpeg/webp, `seed`, `safety_tolerance` | $0.039/image. Output also has `description`. Edit = `fal-ai/nano-banana/edit` (fields **UNVERIFIED**, likely `image_urls`). Newer variants are listed: `nano-banana-pro`, Nano Banana 2/2.1 |
| `fal-ai/bytedance/seedream/v4/text-to-image` | **`prompt`**, `image_size` (enums + `auto`,`auto_2K`,`auto_4K`, or w/h from 960²–4096²), `num_images`, `max_images`, `seed`, `enable_safety_checker`, `enhance_prompt_mode` | $0.03/image |

Latency for all fal models: not documented (**UNVERIFIED**).
Docs: fal.ai/docs/model-endpoints/queue, fal.ai/docs/documentation/model-apis/fal-cdn, fal.ai/models/<id>/api, github fal-ai/fal `fal_client/client.py`

---

## 5. Stability AI (3D image→3D; images). Verified from the official OpenAPI spec (`https://api.stability.ai/v2alpha/openapi`, version v2beta)

| Item | Value |
|---|---|
| Base URL | `https://api.stability.ai` |
| Auth | `Authorization: Bearer sk-...` |
| Env var | `STABILITY_API_KEY` (the name of the spec's security scheme) |
| Async | **No, synchronous.** The response body is the file itself |
| Request | **multipart/form-data** (with `requests`, send `files=` and `data=`; at least one file part is needed, use `files={"none": ''}` for text-only calls) |
| Limits | 150 requests / 10 s (HTTP 429). Request ≤10 MiB (HTTP 413) |
| Errors | JSON `{"id": "...", "name": "bad_request", "errors": ["..."]}`. 400 / 403 (moderation) / 413 / 422 / 429 / 500 |

**3D**
| Endpoint | Fields | Output | Credits |
|---|---|---|---|
| `POST /v2beta/3d/stable-fast-3d` | **`image`** (file: jpeg/png/webp, ≥64 px per side), `texture_resolution` `512`\|`1024`(def)\|`2048`, `foreground_ratio` 0.1–1 (def 0.85), `remesh` `none`\|`triangle`\|`quad`, `vertex_count` -1..20000 | 200 **binary GLB** (`model/gltf-binary`) | 10 |
| `POST /v2beta/3d/stable-point-aware-3d` (SPAR3D) | **`image`**, `texture_resolution`, `foreground_ratio` 1–2 (def 1.3), `remesh`, `target_type` `none`\|`vertex`\|`face`, `target_count` 100–20000 (def 1000), `guidance_scale` 1–10 (def 3), `seed` 0–4294967294 (0 = random) | binary GLB | 4 |

No text→3D (chain an image model first).

**Image** (`Accept: image/*` returns raw bytes; `Accept: application/json` returns `{"image": "<base64>", "seed": n, "finish_reason": "SUCCESS"|"CONTENT_FILTERED"}`)
| Endpoint | Fields (req **bold**) | Credits |
|---|---|---|
| `POST /v2beta/stable-image/generate/core` | **`prompt`**, `aspect_ratio` (21:9,16:9,3:2,5:4,1:1,4:5,2:3,9:16,9:21), `negative_prompt`, `seed`, `style_preset` (e.g. `3d-model`,`photographic`,`digital-art`,`tile-texture`,…), `output_format` `png`(def)\|`jpeg`\|`webp` | 3 (1.5 MP) |
| `POST /v2beta/stable-image/generate/ultra` | **`prompt`**, same as Core plus optional `image` and `strength` (img2img) | 8 (1 MP) |
| `POST /v2beta/stable-image/generate/sd3` | **`prompt`**, `mode` `text-to-image`\|`image-to-image`, `model` `sd3.5-large`(def)\|`sd3.5-large-turbo`\|`sd3.5-medium`, `cfg_scale`, `aspect_ratio`, `seed`, `negative_prompt`, `style_preset`, `output_format` | large 6.5, turbo 4, medium 3.5, flash 2.5 |

1 credit = $0.01: **UNVERIFIED** (the pricing page is a JS app). Optional headers: `stability-client-id`, `stability-client-user-id`, `stability-client-version`. Latency is not documented (SF3D is advertised as fast, **UNVERIFIED**). Failed generations are not charged.

```python
r = requests.post("https://api.stability.ai/v2beta/3d/stable-fast-3d",
    headers={"Authorization": f"Bearer {key}"},
    files={"image": open("in.png","rb")}, data={"texture_resolution":"1024","remesh":"none"})
r.raise_for_status(); open("out.glb","wb").write(r.content)
```

---

## 6. Replicate (generic predictions API)

| Item | Value |
|---|---|
| Base URL | `https://api.replicate.com/v1` |
| Auth | `Authorization: Bearer r8_...` |
| Env var | `REPLICATE_API_TOKEN` (SDK convention) |
| Async | Yes, or sync-ish with `Prefer: wait=N` (N = 1–60 s). If the run is not done in time, the response comes back with status `starting`/`processing`, so keep polling |

- **Official models:** `POST /v1/models/{owner}/{name}/predictions`, body `{"input":{...}}`
- **Community models (need a version):** `POST /v1/predictions`, body `{"version":"<64-hex>" or "owner/name:<64-hex>","input":{...}}`
- Optional: `webhook`, `webhook_events_filter` (`start`,`output`,`logs`,`completed`), header `Cancel-After: 5m` (min 5 s).
- **Poll:** `GET /v1/predictions/{id}` (or `urls.get`). `status`: `starting`, `processing` | `succeeded` | `failed`, `canceled`. Error text is in `error`.
- **Files in:** an HTTP URL, or a **data URI for ≤256 KB** (larger files need a URL).
- **Files out:** `output` (shape depends on the model) holds URLs on `replicate.delivery`. Fetching them **needs the Authorization header**. API predictions' inputs and outputs are **deleted after 1 hour**.
- **Rate limits:** create prediction 600/min; other endpoints 3000/min; 429 when exceeded.
- Error body format is not detailed on the page (**UNVERIFIED**; likely `{"title","detail","status"}`, as the 401 response showed).

**Concrete models** (schemas scraped from replicate.com/{model}/api on 2026-10-17; version hashes can change, so re-check)
| Model | Kind | Call | Input | Output |
|---|---|---|---|---|
| `firtoz/trellis` (community, A100) | image→3D | `/v1/predictions`, version `e8f6c45206993f297372f5436b90350817bd9b4a0d52d2a76df50c1c8afa2b3c` | **`images`** (array of URI), `seed` 0, `randomize_seed` true, **`generate_model`: set true** (def false!), `generate_color` true, `texture_size` 1024, `mesh_simplify` 0.95, `ss_*`/`slat_*` steps & guidance, `save_gaussian_ply` | `output.model_file` (GLB URI); also `color_video`, `gaussian_ply`, … |
| `tencent/hunyuan3d-2` (community, L40S) | image→3D (**geometry only**, no texture input) | version `b1b9449a1277e10402781c5d41eb30c0a0683504fb23fab591ca9dfc2aabe1cb` | **`image`**, `steps` 50, `guidance_scale` 5.5, `seed` 1234, `octree_resolution` 256/384/512, `remove_background` true | `output.mesh` (URI; GLB format **UNVERIFIED**) |
| `ndreca/hunyuan3d-2.1` (community, L40S) | image→3D with PBR texture | version `895e514f953d39e8b5bfb859df9313481ad3fa3a8631e5c54c7e5c9c85a6aa9f` | **`image`**, `generate_texture` true, `max_facenum` 20000, `octree_resolution`, `seed`, `steps`, `guidance_scale` | `output.mesh` |
| `black-forest-labs/flux-1.1-pro` (official) | text→image | `/v1/models/black-forest-labs/flux-1.1-pro/predictions` | **`prompt`**, `aspect_ratio` (`custom`,`1:1`,`16:9`,`3:2`,`2:3`,`4:5`,`5:4`,`9:16`,`3:4`,`4:3`), `width`/`height` (custom only), `output_format` `webp`(def)\|`jpg`\|`png`, `output_quality` 80, `safety_tolerance` 1–6 (def 2), `seed`, `prompt_upsampling`, `image_prompt` | `output` = **single URI string**. $0.04/image (page) |
| `black-forest-labs/flux-schnell` (official) | text→image | `/v1/models/black-forest-labs/flux-schnell/predictions` | **`prompt`**, `aspect_ratio`, `num_outputs` 1, `num_inference_steps` 4, `seed`, `output_format`, `megapixels` "1"\|"0.25", `go_fast` | `output` = **array of URI** |

Community model pricing is per GPU-second (**UNVERIFIED** amounts). Latency is **UNVERIFIED** (cold boots can add minutes).
Docs: replicate.com/docs/reference/http

---

## 7. OpenAI Images

| Item | Value |
|---|---|
| Endpoint | `POST https://api.openai.com/v1/images/generations` (JSON) |
| Auth | `Authorization: Bearer sk-...` |
| Env var | `OPENAI_API_KEY` |
| Async | No, synchronous. The docs say complex prompts can take **up to 2 min**, so set the timeout to 180 s or more. Streaming is available with `stream:true` and `partial_images` 0–3 |

Fields: `model` (**specify it explicitly**): `gpt-image-1`, `gpt-image-1-mini`, `gpt-image-1.5`, `gpt-image-2`, `gpt-image-2-2026-04-21`, `gpt-image-2.5-sunburst`, `gpt-image-2.5-flare` (and their -2026-09-08 snapshots), `chatgpt-image-latest`. **dall-e-2/3 were retired 2026-05-12.**
`prompt` (≤32000 chars), `n` 1–10, `size` (`1024x1024`, `1536x1024`, `1024x1536`, `auto`; gpt-image-2/2.5 also take arbitrary `WxH` with sides divisible by 16, ratio between 1:3 and 3:1, max 3840x2160).
`quality`: `low`|`medium`|`high`|`auto`(def). 2.5 models add `xhigh` and `max`.
**`background`: `transparent`|`opaque`|`auto`(def). Transparent needs `output_format` `png` or `webp`.** Transparency is in *preview* for gpt-image-2. Which other models support it is only stated as "supported GPT Image models" (gpt-image-1 historically yes: **UNVERIFIED per-model**).
`output_format` `png`(def)|`jpeg`|`webp`, `output_compression` 0–100 (jpeg/webp), `moderation` `auto`|`low`, `safety_identifier`. `response_format` is NOT supported for GPT image models (they always return base64).

```json
{"model":"gpt-image-1","prompt":"embroidered rose patch, isolated","size":"1024x1024",
 "quality":"medium","background":"transparent","output_format":"png"}
→ {"created":..., "background":"transparent", "output_format":"png", "data":[{"b64_json":"iVBOR..."}], "usage":{...}}
```
Result: `base64.b64decode(resp["data"][0]["b64_json"])` gives the PNG bytes.
Errors: `{"error":{"message","type","param","code"}}` (standard OpenAI format, not re-read here: **UNVERIFIED**).
Pricing: token based. gpt-image-2: $4 per 1M image input tokens / $15 per 1M image output tokens (Batch table); gpt-image-2.5: $8 / $30. Per-image cost of gpt-image-1/-mini is **UNVERIFIED** (not found on the current pricing page).
Docs: developers.openai.com/api/reference/resources/images/methods/generate, developers.openai.com/api/docs/guides/image-generation, developers.openai.com/api/docs/pricing

---

## 8. Google Gemini image generation ("Nano Banana")

| Item | Value |
|---|---|
| Endpoint | `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` |
| Auth | header `x-goog-api-key: <key>` (the API reference curl examples also use `?key=`) |
| Env var | `GEMINI_API_KEY` |
| Async | No, synchronous (a Batch API also exists at 50% price) |

**Model ids** (from the models/pricing pages): `gemini-2.5-flash-image` (Nano Banana, now labeled legacy), `gemini-3.1-flash-image` (Nano Banana 2), `gemini-3.1-flash-lite-image`, `gemini-3-pro-image`, and Nano Banana 2.1 (`gemini-nano-banana-2.1` on the models page vs `nano-banana-2.1` on the pricing page: **verify which string works**).
**Imagen (incl. `imagen-4.0-generate-001` `:predict`) is SHUT DOWN in the Gemini API** per ai.google.dev/gemini-api/docs/imagen. Do not implement it.

```json
POST .../models/gemini-2.5-flash-image:generateContent
{"contents":[{"parts":[{"text":"a red silk scarf, studio photo"},
   {"inline_data":{"mime_type":"image/png","data":"<base64, optional reference image>"}}]}],
 "generationConfig":{"responseModalities":["TEXT","IMAGE"],
   "imageConfig":{"aspectRatio":"1:1","imageSize":"1K"}}}
```
- `responseModalities` is in `GenerationConfig` (enum Modality). Whether `["IMAGE"]` alone is accepted per model is **UNVERIFIED**, so send `["TEXT","IMAGE"]`.
- `imageConfig.aspectRatio`: 1:1, 1:4, 4:1, 1:8, 8:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9. `imageConfig.imageSize`: `512`, `1K`(def), `2K`, `4K` (uppercase K). Per-model support varies: 512 only on 3.1-flash-image, flash-lite is 1K only, and 2.5-flash-image likely ignores imageSize (**UNVERIFIED**).
- **Result:** iterate `candidates[0].content.parts[]` and take the part with `inlineData` (`{mimeType:"image/png", data:<base64>}`). Text parts may come with it. No image → check `candidates[0].finishReason` (`IMAGE_SAFETY`, `IMAGE_PROHIBITED_CONTENT`, `NO_IMAGE`, `IMAGE_OTHER`, `IMAGE_RECITATION`) and `promptFeedback.blockReason`.
- Output always carries a SynthID watermark. A newer "Interactions API" (`POST /v1beta/interactions`, with `response_format:{type:"image",aspect_ratio,image_size}` and `output_image.data`) is what the image-generation guide now shows; generateContent is still documented in the API reference.
- Errors: Google standard `{"error":{"code","message","status"}}` (**UNVERIFIED**, not re-read).
- **Pricing (Standard, per image):** 2.5-flash-image $0.039. 3.1-flash-image $0.045 (0.5K) / $0.067 (1K) / $0.101 (2K) / $0.151 (4K). nano-banana-2.1 $0.0336 (1K) / $0.0504 (2K) / $0.113 (4K). 3-pro-image $0.134 (1K/2K) / $0.24 (4K). Batch is about half.
Docs: ai.google.dev/api/generate-content, ai.google.dev/gemini-api/docs/{image-generation, imagen, pricing, models}

---

## 9. Black Forest Labs (direct FLUX API)

| Item | Value |
|---|---|
| Base URL | `https://api.bfl.ai` (global, recommended); `api.eu.bfl.ai`, `api.us.bfl.ai` |
| Auth | header `x-key: <key>` |
| Env var | `BFL_API_KEY` |
| Async | Yes. Submit returns `id` + `polling_url`. **Always poll the returned `polling_url`**, not a constructed URL. Webhook via `webhook_url`/`webhook_secret` |

Endpoints: `POST /v1/flux-2-pro`, `/v1/flux-2-max`, `/v1/flux-2-flex`, `/v1/flux-pro-1.1`, `/v1/flux-pro-1.1-ultra`, `/v1/flux-kontext-pro`, `/v1/flux-kontext-max`, `/v1/flux-dev`, `/v1/flux-2-klein-4b`/`-9b`.
**flux-2-pro body:** `prompt` (req), `width`/`height` (min 64; def 0 = auto), `seed`, `safety_tolerance` 0–7 (def 2; values above what your account is approved for return 422), `output_format` `jpeg`(def)|`png`|`webp`, `input_image` … `input_image_8` (reference/edit images; documented only as "path to the input image", so whether it takes base64 or a URL is **UNVERIFIED**), `disable_pup`, `webhook_url`, `webhook_secret`. flux-pro-1.1 fields (`prompt_upsampling`, etc.) are **UNVERIFIED** (not fetched); assume prompt/width/height/seed/output_format.
Submit response: `{"id","polling_url","cost","input_mp","output_mp"}` (cost is in credits).

**Poll:** `GET {polling_url}` with `x-key` every 0.5–1 s (equivalent to `GET /v1/get_result?id=`).
`status` values: `Pending`, `Reasoning`, `Generating` (in progress) | `Ready` | `Error`, `Request Moderated`, `Content Moderated`, `Task not found`, `No Card Generated` (terminal). The quickstart also checks `Failed`.
**Result:** `result.sample` is a signed URL **valid 10 min**, served from `delivery.*.bfl.ai` with no CORS. Format follows `output_format` (use `png`).
Errors: 402 out of credits, 422 validation, 429 when more than **24 active tasks** (flux-kontext-max: 6).
Pricing: 1 credit = $0.01. FLUX.2 is per megapixel; per-model numbers did not load (**UNVERIFIED**; fal's resale price for flux-2-pro is $0.03 for the first MP). Latency is not stated (**UNVERIFIED**).
Docs: docs.bfl.ai/quick_start/generating_images, docs.bfl.ai/api-reference/models/generate-or-edit-an-image-with-flux2-[pro], docs.bfl.ai/api-reference/utility/get-result, docs.bfl.ai/quick_start/pricing

---

## 10. Ideogram

| Item | Value |
|---|---|
| Base URL | `https://api.ideogram.ai` |
| Auth | header `Api-Key: <key>` |
| Env var | `IDEOGRAM_API_KEY` |
| Async | **Sync by default.** `async=true` or a `webhook_url` returns only `generation_id`; then poll `GET /v2/generations/{generation_id}` (`pending` → `completed`/`failed`) |

**Current (v2):** `POST /v2/image/generate/ideogram-3`, **multipart/form-data**. Newer models: `/v2/image/generate/ideogram-4`, `ideogram-4-5`.
Fields: `prompt` (req), `negative_prompt`, `seed`, `aspect_ratio` (cannot combine with `resolution`), `resolution`, `rendering_speed`, `magic_prompt` (`auto`|`on`|`off`), `num_images` (def 1), `style_type`, `style_preset`, `style_codes`, `color_palette`, `style_reference_images` (≤10 files, 25 MB each), `enable_copyright_detection`, `async`, `webhook_url`.
Enums are listed on the **transparent** endpoint page (and probably shared: UNVERIFIED for ideogram-3): `aspect_ratio` `1x1`(def), `16x9`, `9x16`, `4x3`, `3x4`, `3x2`, `2x3`, `4x5`, `5x4`, `16x10`, `10x16`, `2x1`, `1x2`, `3x1`, `1x3`, `auto`. `rendering_speed` `turbo`|`default`|`quality` (lowercase in v2; v1 used `TURBO`/`DEFAULT`/`QUALITY`). `style_type` `AUTO`/`GENERAL`/`REALISTIC`/`DESIGN`/`FICTION` (from v1 page).
**Transparent PNG:** `POST /v2/image/generate/ideogram-3-transparent` (**JSON** body; same fields plus `upscale_factor` `x1`|`x2`|`x4`). Also `/v2/image/generate/ideogram-4-transparent`. Useful for decals/patches.
Response: `{"generation_id","seed","data":[{"url","prompt","resolution":"1024x1024","is_image_safe","seed"}]}`. Use `data[0].url`; it is **empty when `is_image_safe` is false**. URLs expire (`exp` query param), so download them.
Legacy v1: `POST /v1/ideogram-v3/generate` (multipart) has the same response with `created` + `data[]`.
Errors: 400, 401, 402 (`reject_reason`: `insufficient_funds`, …), 422 safety, 429 (`reject_reason` `inflight_limit` etc.), 503. Default limit: **10 in-flight requests**.
Pricing: pay-as-you-go credits are $0.01 each; per-image API prices did not load (**UNVERIFIED**). Pass `?dry_run=true` to get a `PriceQuote` without billing (useful for an offline client test with a real key).
Docs: developer.ideogram.ai/v2/ideogram-api/api-overview.md, developer.ideogram.ai/v2/api-reference/images/generate/{ideogram-3, ideogram-3-transparent}.md, OpenAPI at developer.ideogram.ai/openapi.json

---

## 11. Recraft

| Item | Value |
|---|---|
| Base URL | `https://external.api.recraft.ai/v1` (OpenAI-compatible shape) |
| Auth | `Authorization: Bearer <token>` |
| Env var | `RECRAFT_API_TOKEN` (vendor's name) |
| Async | No, synchronous |

`POST /images/generations` (JSON); `/images/generations/vector` is for `_vector` models only and `/images/generations/raster` for the rest.
Fields: `prompt` (req), `n` 1–6, `model` (def `recraftv4_1`; also `recraftv4_1_flash`, `recraftv4_1_utility`, `recraftv4`, `recraftv4_styles`, `*_pro` (2K), `recraftv3`, `recraftv2`, and `_vector` variants such as `recraftv3_vector`; other `_vector` ids are **UNVERIFIED**), `style` (`vector_illustration`, `digital_illustration`, `realistic_image`, `icon`, `any`; which styles apply depends on the model), `style_id`, `size` (`w:h` preferred, e.g. `1:1`, or `WxH` from the table: 1K models 1024x1024 etc.), `negative_prompt` (V2/V3), `random_seed`, `response_format` `url`(def)|`b64_json`, `image_format` `webp`(def)|`png`, `text_layout` (V3), `controls` (`colors:[{rgb:[r,g,b]}]`, `background_color`, `artistic_level` 0–5, `no_text`). `substyle` is not documented (**UNVERIFIED**).
```json
{"prompt":"floral embroidery motif","model":"recraftv3","style":"vector_illustration","size":"1:1","image_format":"png"}
→ {"data":[{"url":"https://..."}]}
```
**Vector models return SVG** ("editable SVG with a `_vector` model"). Vector sizes are `w:h` only. Raster: set `image_format:"png"`. Our pipeline needs PNG, so rasterize the SVG (e.g. cairosvg) or use a raster model.
URLs are kept about **24 h**. Limits: **100 images/min and 5 req/s per user**. Utilities: `POST /images/removeBackground` ($0.01), `POST /images/vectorize` ($0.01).
Pricing per image: V4.1 $0.035 raster / $0.08 vector; V4.1 Flash $0.007 (about 1.3 s); V4 $0.04 / $0.08; V3 $0.04 / $0.08; V2 $0.022 / $0.044; Pro (2K) $0.21–0.30. Error format: **UNVERIFIED**.
Docs: recraft.ai/docs/api-reference/{endpoints, getting-started, appendix, pricing}

---

## Summary

| Provider | Kind | text→ | image→ | Output | Auth env var | Async? |
|---|---|---|---|---|---|---|
| Tripo3D v3 | 3D | ✅ | ✅ (upload→file_token or URL) | GLB `output.model_url` | `TRIPO_API_KEY` | poll `/v3/tasks/{id}` |
| Meshy | 3D | ✅ (preview+refine) | ✅ (URL or data URI) | GLB `model_urls.glb` | `MESHY_API_KEY` | poll GET |
| Hyper3D Rodin | 3D | ✅ | ✅ (multipart files) | GLB via `/download` `list[]` | `RODIN_API_KEY` | poll `/status` → `/download` |
| fal Hunyuan3D 3.1 pro/rapid, v3 | 3D | ✅ | ✅ (URL/data URI) | GLB `model_glb.url` / `model_urls.glb.url` | `FAL_KEY` | queue |
| fal TRELLIS / TRELLIS-2 | 3D | ❌ | ✅ | GLB `model_mesh.url` / `model_glb.url` | `FAL_KEY` | queue |
| Stability SF3D / SPAR3D | 3D | ❌ | ✅ (multipart) | GLB binary body | `STABILITY_API_KEY` | sync |
| Replicate firtoz/trellis, hunyuan3d | 3D | ❌ | ✅ (URL/data URI ≤256 KB) | `output.model_file` / `output.mesh` | `REPLICATE_API_TOKEN` | poll / `Prefer: wait` |
| fal FLUX / nano-banana / seedream / kontext | image | ✅ | kontext edit | `images[0].url` | `FAL_KEY` | queue |
| Stability Core/Ultra/SD3.5 | image | ✅ | Ultra/SD3 img2img | PNG binary (or JSON b64) | `STABILITY_API_KEY` | sync |
| Replicate FLUX 1.1 pro / schnell | image | ✅ | – | `output` URI / `output[0]` | `REPLICATE_API_TOKEN` | poll / wait |
| OpenAI gpt-image-* | image | ✅ (transparent bg) | (edits endpoint, not covered) | `data[0].b64_json` PNG | `OPENAI_API_KEY` | sync |
| Google Gemini image | image | ✅ | ✅ inline_data | `parts[].inlineData.data` b64 | `GEMINI_API_KEY` | sync |
| Google Imagen 4 | image | **shut down** | – | – | – | – |
| BFL FLUX direct | image | ✅ | `input_image*` | `result.sample` URL (10 min) | `BFL_API_KEY` | poll `polling_url` |
| Ideogram v2 | image | ✅ (+transparent endpoint) | style refs | `data[0].url` | `IDEOGRAM_API_KEY` | sync (opt. async) |
| Recraft | image | ✅ (SVG via `_vector`) | – | `data[0].url` (webp/png/svg) | `RECRAFT_API_TOKEN` | sync |

---

# Additions (researched 2026-10-25)

Same rules as above: taken from vendor docs, **not tested with a live key**. Every adapter is covered by a
fake-server test in `backend/workers/cloud/tests/test_providers.py`. The Tencent signature is checked
byte for byte against the official `tencentcloud-sdk-python` signer.

## 4b. fal.ai — more 3D models (same queue API and `FAL_KEY`)

Every fal output file is `{url, content_type, file_name, file_size}`. The GLB key differs per model, so the
adapter tries `model_glb` → `model_mesh` → `model_urls.glb` → `model_urls.pbr_model` → `individual_glbs[0]`
→ `model`, skipping any file whose type or name says OBJ/FBX.

| Engine | model_id | Image field | Main options we send | GLB at | Price |
|---|---|---|---|---|---|
| `cloud-faltripo-*` | `tripo3d/h3.1/{text,image}-to-3d` | `image_url` | `texture`, `pbr`, `texture_quality`/`geometry_quality` (`detailed` on high), `model_seed`/`texture_seed` | `model_mesh` (FBX if `quad`) / `model_urls.glb` | text $0.10–0.30, image $0.20–0.40, +$0.20 detailed |
| `cloud-falmeshy-*` | `meshy/v7.1/{text,image}-to-3d` | `image_url` | `target_polycount` 10k/30k/100k, `enable_pbr`, image `should_texture`, text `mode` full/preview (prompt ≤600) | `model_glb` | $0.80 bare / $1.20 textured |
| `cloud-falrodin-text` | `fal-ai/hyper3d/rodin/v2.5/text-to-3d` | – | `tier` `Gen-2.5-Low/Medium/High`, `material` PBR/None, `geometry_file_format` glb, `seed` 0–65535 | `model_mesh` | $0.40 (+$0.80 HighPack) |
| `cloud-falrodin-image` | `fal-ai/hyper3d/rodin/v2.5` (no `/image-to-3d` suffix: 404) | `image_urls` (list ≤5) | as above | `model_mesh` | $0.40 |
| `cloud-falhunyuanrapid-image` | `fal-ai/hunyuan-3d/v3.1/rapid/image-to-3d` | `input_image_url` | `enable_pbr`, `enable_geometry` | `model_urls.glb` (`model_glb` may be OBJ) | $0.225, +$0.15 PBR |
| `cloud-falhitem3d-image` | `hitem3d/hi3d/v3.0/image-to-3d` | `image_url` | `enable_texture`, `enable_pbr`, `face_count` 300k/1M/2M, `export_format` glb | `model_mesh` | $2.10 (2048quality) – $9.10 (master) |
| `cloud-falsam3d-image` | `fal-ai/sam-3/3d-objects` | `image_url` | `prompt` (segmentation text, default "car" → we send "garment"), `export_textured_glb` | `model_glb` or `individual_glbs[i]` | "$0.02 per unit" (unit UNVERIFIED) |
| `cloud-falpixal3d-image` | `fal-ai/pixal3d` | `image_url` | `resolution` 1024/1536, `seed` | `model_glb` | $0.30 / $0.42 |

Also on fal, not wired: multi-view variants (`tripo3d/h3.1/multiview-to-3d`, `meshy/v7.1/multi-image-to-3d`,
`hitem3d/hi3d/v3.0/multi-view-to-3d`), Tripo P2 low-poly (`tripo3d/p2/*`, $1.00–1.30), Rodin fast
(`.../v2.5/fast`, $0.10), `fal-ai/reconviagen-0.5`, 3D-to-3D tools (retexture, rigging, remesh, part split).
`fal-ai/bytedance/seed3d/image-to-3d` is missing from fal's listing (probably deprecated) → Seed3D goes through Atlas Cloud.

## 6b. Replicate — more 3D models (`REPLICATE_API_TOKEN`)

| Engine | Model | Endpoint | Input | Output | Price |
|---|---|---|---|---|---|
| `cloud-replicatehunyuan-*` | `tencent/hunyuan-3d-3.1` (**official**) | `POST /v1/models/tencent/hunyuan-3d-3.1/predictions` | `prompt` **or** `image`, `enable_pbr`, `face_count` 40k–1.5M, `generate_type` Normal/Geometry | URL string (.glb) | $0.50 |
| `cloud-replicatetrellis2-image` | `fishwowater/trellis2` (community) | `POST /v1/predictions` + version `52e1ad68…b226` | `image`, `pipeline_type` 512/1024_cascade/1536_cascade, `texture_size`, `generate_video:false`, `seed`/`randomize_seed` | `{model_file, video, no_background_image}` | ~$0.88 (A100 time) |

Not on Replicate (slugs 404): official TRELLIS.2, Tripo, Meshy, Rodin 2.5, Seed3D, Hitem3D, SF3D, SAM-3D.
`hyper3d/rodin` exists but is Gen-2 (not wired; Rodin 2.5 is on fal and direct).

## 12. Tencent HY 3D Global (Hunyuan 3D Pro, official)

| Item | Value |
|---|---|
| Endpoint | `POST https://hunyuan.intl.tencentcloudapi.com/` (body JSON), `X-TC-Version: 2023-09-01`, `X-TC-Region: ap-singapore` (also `eu-frankfurt`, `na-siliconvalley`) |
| Auth | TC3-HMAC-SHA256 with SecretId + SecretKey; service `hunyuan`; signed headers `content-type;host` |
| Env var | `TENCENTCLOUD_API_KEY` = `SecretId:SecretKey` (one line) |
| Submit | `X-TC-Action: SubmitHunyuanTo3DProJob`: `Model` "3.0"/"3.1", `Prompt` (≤1024) **or** `ImageBase64`/`ImageUrl` (128–5000 px, ≤6 MB raw), `MultiViewImages[]`, `EnablePBR`, `FaceCount` 3000–1.5M (def 500k), `GenerateType` Normal/LowPoly/Geometry/Sketch → `Response.JobId` (24 h) |
| Poll | `QueryHunyuanTo3DProJob` `{"JobId"}` → `Status` WAIT/RUN/FAIL/DONE, `ErrorCode`, `ErrorMessage`, `ResultFile3Ds[]{Type, Url, PreviewImageUrl}` → pick `Type == "GLB"` |
| Errors | `Response.Error{Code, Message}` (e.g. `AuthFailure.SignatureFailure`, `RequestLimitExceeded`) |
| Limits | 20 req/s per action; 3 concurrent Pro jobs |
| Price | Pro Normal 25 credits, Geometry 15, +10 each for PBR / multi-view / FaceCount; $0.02 per credit postpaid; 200 free credits once |
| Also | Rapid (`SubmitHunyuanTo3DRapidJob`, prompt ≤200, `ResultFormat`), part split, smart topology, rigging, UV, format convert |
| Docs | tencentcloud.com/document/api/1284/75540 (submit), /75541 (query), /75535 (signature), product/1284/75281 (billing) |

## 13. Hitem3D (Hi3D by Math Magic, direct)

| Item | Value |
|---|---|
| Base | `https://api.hitem3d.ai/open-api/v1` (docs moved to docs.hi3d.ai) |
| Auth | `POST /auth/token` with `Authorization: Basic base64(client_id:client_secret)` → `data.accessToken`; then `Authorization: Bearer <token>` |
| Env var | `HITEM3D_API_KEY` = `client_id:client_secret` |
| Submit | `POST /submit-task` multipart: `images` (file, ≤20 MB) or `multi_images` (≤4, + `multi_images_bit`), `request_type` 1 mesh / 3 mesh+texture, `model` `hi3dv3.0` (also hitem3dv1.5/2.0/2.1), `resolution` `2048quality`/`2048master`, `face` 100k–5M, **`format` 2 = GLB (default 1 = OBJ)**, `pbr` 0/1, `shading`, `rmbg` → `data.task_id` |
| Poll | `GET /query-task?task_id=` → `data.state` created/queueing/processing/success/failed, `data.url` (1 h), `data.cover_url` |
| Envelope | `{"code":200,"data":{…},"msg"|"message":"success"}`; `30010000` no balance, `40010000` bad credentials, `50010001` generate failed (refunded) |
| Price | $0.02/credit: v3.0 2048quality 45 credits ($0.90), 2048master 145 ($2.90); prepaid package required |

## 14. Neural4D (DreamTech, OpenAPI v1)

| Item | Value |
|---|---|
| Base | `https://api.neural4d.com/openapi/v1`, `Authorization: Bearer <key>` |
| Env var | `NEURAL4D_API_KEY` (paid subscription required, else 403 `subscription_required`) |
| Upload | `POST /files` multipart `file` → `id` (base64 not accepted) |
| Submit | `POST /3dmodels/generations` (JSON only): `model` `dreamtech/neural4d-2.5`, `prompt` (≤500) **or** `input_references:[{"type":"image","file_id"}]`, `with_texture`, `with_pbr`, `mesh_quality` standard/high/extra_high, `topology`, `target_polycount`, `pose`, `n` → 202 `{id, status}` |
| Poll | `GET /tasks/task-info?id=` → `status` queued/processing/succeeded/failed, GLB at `output.models[0].model_urls.glb` |
| Errors | `{"error":{code,message}}`; on 500 `task_registration_failed` do **not** resubmit (already queued and billed) |
| Price | ~30 credits per model in doc examples; plan prices not readable (JS) |

## 15. 3D AI Studio

| Item | Value |
|---|---|
| Base | `https://api.3daistudio.com/v1`, `Authorization: Bearer <key>` |
| Env var | `THREEDAISTUDIO_API_KEY` |
| Hunyuan 3D Pro | `POST /3d-models/tencent/generate/pro/`: `model` "3.1", `prompt` **or** `image` (data URI), `enable_pbr`, `face_count`, `generate_type` → GLB. 60 credits (+20 PBR, +20 multi-view) |
| TRELLIS.2 | `POST /3d-models/trellis2/generate/`: `image`/`image_url`, `resolution` "512"/"1024"/"1536", `textures` (default **false**), `texture_size`, `seed` → GLB. 15–55 credits |
| Also | Hunyuan Rapid (returns a ZIP of OBJ), Hitem3D v3 (125–650 credits), Tripo 3.0–3.2 |
| Poll | `GET /generation-request/{task_id}/status/` → `status` PENDING/IN_PROGRESS/FINISHED/FAILED, `results[0].asset` (`asset_type` 3D_MODEL = GLB, ARCHIVE = ZIP; 24 h) |
| Limits | **3 requests per minute** by default → the adapter polls every 25 s |
| Price | credits; USD per credit not published |

## 16. Atlas Cloud (ByteDance Seed3D 2.0)

| Item | Value |
|---|---|
| Base | `https://api.atlascloud.ai/api/v1/model`, `Authorization: Bearer <key>` |
| Env var | `ATLASCLOUD_API_KEY` |
| Submit | `POST /generateImage` (same path for every model): `model` `bytedance/seed3d-v2.0/image-to-3d`, `image` (URL or data URI, ≤10 MB), `subdivision_level` low/medium/high (~100k/500k/1M faces), `file_format` glb → `data.id` (fallback `id`) |
| Poll | `GET /prediction/{id}` → `data.status` created/processing/completed(/succeeded)/failed, `data.outputs[0]` |
| Output | **a ZIP** holding one GLB → the adapter unzips it |
| Price | $0.353 per generation. Also hosts Hunyuan3D Rapid/Pro (listed price $0.02 looks wrong, UNVERIFIED) |

## 17. BytePlus ModelArk (Hyper3D Rodin Gen-2)

| Item | Value |
|---|---|
| Base | `https://ark.ap-southeast.bytepluses.com/api/v3`, `Authorization: Bearer <ARK key>` |
| Env var | `ARK_API_KEY`. Supported regions include **TR**; US and EU are not listed |
| Submit | `POST /contents/generations/tasks`: `model` `hyper3d-gen2-260112`, `content[]` = text item (English prompt ≤400 + flags `--material PBR --mesh_mode Raw --ff glb --sl medium`) and optional `image_url` items (URL or data URI, ≤5), top-level `seed` 0–65535 |
| Poll | `GET /contents/generations/tasks/{id}` → `status` queued/running/succeeded/failed/cancelled/expired, `content.file_url` (24 h) |
| Price | ~$0.40 per model. Also `hitem3d-2-0-251223` (Hitem3D v2.0, image **URL only**, not wired) |

## Checked and not added

| Provider | Why |
|---|---|
| CSM.ai (Cube) | Bought by Google (Jan 2026); csm.ai domains no longer resolve (2026-10-25) |
| Luma Genie | No production API |
| Spline | No public generation API (export only) |
| Kaedim | Managed studio service, not a self-serve API |
| Sloyd | Catalog + sliders, no free-text or photo input; API terms not published |

## Updated summary (3D, all providers)

| Provider | text→3D | image→3D | Env var |
|---|---|---|---|
| Tripo3D (direct) | ✅ | ✅ | `TRIPO_API_KEY` |
| Meshy (direct) | ✅ | ✅ | `MESHY_API_KEY` |
| Hyper3D Rodin (direct) | ✅ | ✅ | `RODIN_API_KEY` |
| fal.ai: Hunyuan3D Pro/Rapid, TRELLIS.2, Tripo H3.1, Meshy 7.1, Rodin 2.5, Hitem3D v3, SAM 3D, Pixal3D | ✅ (Hunyuan, Tripo, Meshy, Rodin) | ✅ | `FAL_KEY` |
| Stability SF3D | ❌ | ✅ | `STABILITY_API_KEY` |
| Replicate: TRELLIS, TRELLIS.2, Hunyuan3D 3.1 | ✅ (Hunyuan) | ✅ | `REPLICATE_API_TOKEN` |
| Tencent HY 3D Pro (official) | ✅ | ✅ | `TENCENTCLOUD_API_KEY` |
| Hitem3D (direct) | ❌ | ✅ | `HITEM3D_API_KEY` |
| Neural4D | ✅ | ✅ | `NEURAL4D_API_KEY` |
| 3D AI Studio: Hunyuan3D Pro, TRELLIS.2 | ✅ (Hunyuan) | ✅ | `THREEDAISTUDIO_API_KEY` |
| Atlas Cloud: Seed3D 2.0 | ❌ | ✅ | `ATLASCLOUD_API_KEY` |
| BytePlus ModelArk: Rodin Gen-2 | ✅ | ✅ | `ARK_API_KEY` |
