# Contributing to 3D AI Lab

Thanks for your interest! Contributions of all kinds are welcome — new generation
engines, languages, export formats, bug fixes, and UI polish.

## Getting set up

See the [README](README.md#quickstart) for the full setup. In short:

```bash
bash infra/scripts/setup-linux.sh         # core: gateway + workers' common code + frontend + .env
infra/scripts/engine.sh install triposr   # one GPU engine (own env)
bash infra/scripts/start-linux.sh         # Redis + gateway + frontend + workers
```

- Gateway (FastAPI): **:9000** · Frontend (Vite): **:3000** · Redis broker.
- Python 3.11 via [`uv`](https://github.com/astral-sh/uv); frontend via [`pnpm`](https://pnpm.io/).
- Tests: `make test` (one command, no GPU needed). Lint: `make lint`.

### Frontend dev

```bash
cd frontend
pnpm dev               # binds 0.0.0.0:$FRONTEND_PORT, proxies /api → gateway
pnpm typecheck         # tsc, no emit
```

## Adding an engine

1. Worker code: `backend/workers/<name>/src/<name>_worker/` (Celery app + engine class).
2. Register it in `backend/common/src/common/engines/registry.py`.
3. Describe install + run in **one file**, `infra/engines/<name>.sh`: upstream URL and
   pinned commit, env type (`venv`/`conda`), Python/torch index, worker module, and
   optional `engine_build` / `engine_weights` / `engine_env` hooks. Local fixes to the
   upstream repo go in `infra/engines/patches/<name>.patch`; a frozen, known-good
   package set in `infra/engines/locks/<name>.txt`.
4. Verify: `infra/scripts/engine.sh install <name> && infra/scripts/engine.sh check <name>`.

Never hard-code machine paths: use `common.config.engines_dir()` for upstream
checkouts/weights and `get_settings()` for data dirs.

## Internationalization

The UI ships with **English** and **Turkish**. The i18n layer is intentionally tiny
and dependency-free — no runtime i18n library.

- Dictionaries live in `frontend/src/i18n/locales/`. `tr.ts` and `en.ts` compose a
  seed plus per-area **part files** under `locales/parts/` (`designer.ts`,
  `generate.ts`, …).
- Keys are dotted `"<area>.<purpose>"` paths, e.g. `"login.title"`. Interpolate with
  `{name}` placeholders: `t("dashboard.confirmDelete", { name })`.
- In a component: `import { useT } from "../i18n"; const { t } = useT();` then
  `t("some.key")`.

**Rule: `tr` and `en` must have identical key sets.** A missing key falls back to
Turkish, then to the raw key — both are visible bugs.

### Adding a language

1. Copy `locales/en.ts` to e.g. `locales/de.ts` and translate every value (keep the
   keys unchanged). Do the same for each part file it imports, or add a parallel set.
2. Register the new `Lang` and dictionary in `frontend/src/i18n/index.tsx` and add it
   to the `LanguageToggle`.

## Code conventions

- Match the style of the file you're editing.
- Keep user-facing strings in the i18n dictionaries, never hard-coded in components.
- Backend: keep engine workers isolated (one model family per worker/queue).

## Pull requests

- Describe what changed and how you verified it (for UI, a real browser check beats a
  passing typecheck).
- Keep PRs focused. Unrelated refactors make review harder.

## License

By contributing, you agree your contributions are licensed under the project's
[MIT License](LICENSE).
