.PHONY: help setup start stop engines frontend gateway test lint clean

help:
	@echo "Targets:"
	@echo "  setup     - One-time core setup (uv env, frontend, FreeSewing, .env)"
	@echo "  start     - Start Redis + gateway + frontend + installed engine workers"
	@echo "  stop      - Stop what 'start' launched"
	@echo "  engines   - List engines and install state (install: infra/scripts/engine.sh install <name>)"
	@echo "  frontend  - Frontend dev server only"
	@echo "  gateway   - Gateway dev server only (auto-reload)"
	@echo "  test      - All backend tests (no GPU needed)"
	@echo "  lint      - Ruff lint"
	@echo "  clean     - Clear caches"

setup:
	bash infra/scripts/setup-linux.sh

start:
	bash infra/scripts/start-linux.sh

stop:
	bash infra/scripts/stop-linux.sh

engines:
	bash infra/scripts/engine.sh list

frontend:
	cd frontend && pnpm dev

gateway:
	uv run uvicorn gateway.main:app --app-dir backend/gateway/src --host 0.0.0.0 --port $${GATEWAY_PORT:-9000} --reload

test:
	uv run pytest

lint:
	uv run ruff check backend/

clean:
	find . -path ./engines -prune -o -type d \( -name __pycache__ -o -name .pytest_cache -o -name .ruff_cache -o -name .vite \) -prune -exec rm -rf {} +
