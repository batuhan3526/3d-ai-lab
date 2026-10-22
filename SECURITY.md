# Security & Responsible Use

3D AI Lab is a **self-hosted generative-AI application** that runs image/text → 3D
and Stable-Diffusion / FLUX-based texturing models locally. Please read this before
exposing it beyond `localhost`.

## Reporting a vulnerability

Report suspected vulnerabilities privately through GitHub's
**Security → Report a vulnerability** (private advisory) on this repository rather
than opening a public issue. Include repro steps and impact. Please allow reasonable time to remediate before public
disclosure.

## Content safety — no filter is active by default

**Disclosure:** unless you set `SAFETY_FILTER=block` (opt-in NSFW check for FLUX
motifs and uploads), the bundled diffusion pipelines (FLUX.1-dev for motifs/decals, and
Stable Diffusion 1.5 via InTeX for texturing) run with **no NSFW / safety checker**.
The texture generators never run a `safety_checker`, so they can produce unfiltered,
harmful, infringing, or NSFW content.

Consequences and expectations:
- **You are responsible** for the prompts you run and the outputs you generate,
  store, and share.
- Do **not** deploy this as a public/multi-tenant service without adding your own
  content moderation and abuse controls.
- Respect each model's **acceptable-use terms** (e.g. FLUX and OpenRAIL-M carry
  use-based restrictions) and applicable law. Do not generate content that is
  illegal, infringing, or targets real people without consent.

## Model licensing = a legal safety surface

Several integrated models are **non-commercial** or **gated**. Using them in a
commercial product, or redistributing their weights, can violate their licenses.
See [`docs/LICENSES.md`](docs/LICENSES.md) and
[`THIRD_PARTY_LICENSES.md`](THIRD_PARTY_LICENSES.md) before shipping.

## Deployment hardening

The default setup binds services to `0.0.0.0` for LAN/Tailscale access. That is
convenient but **not** hardened for a hostile network. Before exposing it:

- **Set a strong `APP_TOKEN`** (bearer auth). Generate one with:
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Never ship the
  placeholder from `.env.example`.
- **Password-protect Redis** and firewall it. By default the broker is
  `redis://127.0.0.1:6379/0` with **no password**; anyone who can reach the Redis
  port can read job prompts and drain/tamper the queue. Use `requirepass` and bind
  Redis to loopback (or a private interface) only.
- **Restrict inbound ports.** Only the frontend (`:3000`) needs to be reachable by
  clients; the gateway (`:9000`) and Redis should stay private
  (e.g. `sudo ufw allow 3000/tcp` and nothing else).
- **Don't expose it to the public internet** without a reverse proxy that adds
  TLS, authentication, and rate limiting.

## Known limitations (unhardened surfaces)

These are documented gaps a self-hoster should be aware of (contributions welcome):

- **No rate limiting / quota / concurrency cap** on `/generate` — a caller on the
  LAN can flood the job queue.
- **Unbounded disk growth** — deletes can leave orphaned files; there is no GC or
  free-space guard. Monitor `data/` size.
- **Public `/{project_id}/mesh` endpoint** spawns an uncapped background thread per
  request (mesh simplify + UV unwrap). It is unauthenticated by design for viewer
  streaming; keep the gateway off untrusted networks.
- **`/health` is static** — it does not probe Redis, workers, or the DB, so an
  uptime monitor can read "healthy" while workers are down.
- **SQLite is the only DB backend.** With many worker processes writing, enable
  WAL + `busy_timeout` (the gateway does this) and keep the DB on a local
  filesystem to avoid "database is locked" / corruption.

## Secrets

Never commit real secrets. `.env` holds `APP_TOKEN`, `HF_TOKEN`, and optionally a
Redis password — it must stay out of version control (it is git-ignored). Rotate
any token that has been exposed.
