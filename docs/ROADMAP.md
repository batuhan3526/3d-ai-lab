# Roadmap & known issues

Status as of 2026-10. Items marked **(verified)** were reproduced on a real setup;
the rest come from development notes and still need a fresh check.

## Known bugs

1. **Mannequin measurements read low.** The 165 cm female base mannequin measures
   ~74 cm chest (realistic ≈ 88 cm). Tailor measurements and fit depend on this —
   look at `clothsim_worker/measure.py`. Highest priority.
2. **Size-ratio guard misses lying-down meshes.** A broken model whose long axis is
   horizontal (short y extent) passes `check_garment_span` and is "dressed" as SUCCESS.
3. **Text → 3D fails on complex garments.** TRELLIS-text produced 0 usable results in
   8 tries for a blouse (e.g. "balloon sleeves" → a hot-air balloon). Working path:
   FLUX product photo ("ghost mannequin", no visible body) → photo → 3D.
4. **Designer default colour `#cccccc` greys out textures** — should default to `#ffffff`.
5. **`/engines/status` is slow (verified).** The gateway pings each family×GPU
   sequentially (~2.5 s timeout each); queues without a worker accumulate unanswered
   `engine.status` messages in Redis. Engines can look "offline" for a minute after
   start-up. Fix: parallel pings + expiring/purged status messages.
6. **Gateway hangs on graceful shutdown** while a WebSocket is open; engine
   enable/disable needs a gateway restart (registry is read at import time).
7. **Possible logic bug:** `common/patterns.py` ~L864 — a closure does not bind loop
   variables `off`/`ph` (ruff B023). ~170 other lint findings are mostly style.
8. **Celery clock-drift / missed-heartbeat warnings** on some hosts (VM clock drift).

## Structural issues

- **VRAM on a single GPU is not scheduled.** All workers share one card; two heavy
  jobs at once can OOM. Today the user frees VRAM manually (Unload models).
- **Engine install recipes:** TripoSR and the clothsim/Blender recipe were verified
  from scratch; the other engines are ported from working installs and need a
  fresh-machine test (FaceAnything's venv recipe is untested).
- **Hardening gaps** (see `SECURITY.md`): no rate limit on `/generate`, orphaned files
  on delete, public mesh endpoint spawns uncapped threads, static `/health`.
- **Untested flows:** cloud engines with a real API key; visual test of bottoms.
- **No CI** — the 537 backend tests are not run automatically.

## Feature ideas (by value for "design → tailor")

1. **One body profile** used everywhere (Atelier, dressing, custom mannequin) instead of
   entering measurements twice.
2. **Design → pattern bridge:** suggest the closest Atelier pattern for an AI design.
3. **Tailor pack:** one PDF with pattern, cut plan, measurement table, 3D renders,
   fabric and notes.
4. **More 3D sewing:** only t-shirt, pencil skirt and circle skirt sew in 3D (3 of 11).
5. **Pattern design details:** sleeve type, collar, length, darts, ruffles (expose more
   FreeSewing options).
6. **Print placement on pattern pieces:** map 3D decals onto the 2D pieces.
7. **Grading** (size runs) and size charts.
8. **Fit map:** tight/loose heat map on the mannequin.
9. **Measurements from photos** (no tape measure).
10. **Fabric cost estimate:** required length × price.
11. **Infra:** VRAM-aware job scheduling with auto-unload, deep health checks, GitHub
    Actions CI, Docker one-command install, cloud API spend tracking.
12. Wire up `flex4dhuman-4d` / `pixworld-scene` once upstream releases them.
