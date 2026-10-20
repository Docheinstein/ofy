# Build and run Ofy. `make help` lists the targets.
#
# Targets rebuild only what is out of date: the backend venv when pyproject.toml/uv.lock change,
# node_modules when package-lock.json changes, the UI when any frontend source is newer than the build.
#
# Extra arguments for the desktop app go in ARGS, e.g. `make run ARGS=--debug`; the web server port in
# PORT, e.g. `make web PORT=9000`.

SHELL := bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := build

ARGS ?=
PORT ?= 8080

VENV := backend/.venv
NODE_MODULES := frontend/node_modules/.package-lock.json
DIST := frontend/dist/index.html
FRONTEND_SRC := $(shell find frontend/src frontend/public -type f) frontend/index.html \
	frontend/package.json $(wildcard frontend/*.config.*)

.PHONY: help build run web dev test clean

help: ## Show this help
	@awk -F ':.*## ' '/^[a-z]+:.*## / { printf "  make %-7s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

build: $(VENV) $(DIST) ## Install backend + frontend dependencies and build the UI (the default)
	@command -v ffmpeg >/dev/null || echo "warning: ffmpeg not found on PATH; downloads will fail until it is installed." >&2

run: build ## Desktop app (native window)
	cd backend && uv run ofy-desktop $(ARGS)

web: build ## Web server only: UI at http://localhost:8080 (PORT=... to change)
	@echo "Ofy web UI: http://localhost:$(PORT)"
	cd backend && OFY_PORT=$(PORT) uv run python -m ofy

# Job control puts each server in its own process group, so the trap can stop the whole tree
# (uv -> python -> uvicorn reloader -> worker, and Vite's node process) with one signal.
# Vite runs directly (not via `npm run`): npm doesn't reliably forward signals to it.
dev: $(VENV) $(NODE_MODULES) ## Backend (auto-reload) on :8080 + Vite (hot reload) on http://localhost:5173; Ctrl-C stops both
	@set -m; \
	trap 'trap - INT TERM EXIT; kill -TERM -- -$$api -$$ui 2>/dev/null || true; wait 2>/dev/null || true' INT TERM EXIT; \
	(cd backend && exec uv run uvicorn ofy.main:app --host 127.0.0.1 --port 8080 --reload --reload-dir src) & api=$$!; \
	(cd frontend && exec ./node_modules/.bin/vite --host 127.0.0.1) & ui=$$!; \
	echo "Dev UI: http://localhost:5173  (API on :8080, both reload on change; Ctrl-C to stop)"; \
	wait -n $$api $$ui  # stop everything as soon as either exits

test: $(VENV) ## Run the backend unit tests
	cd backend && uv run pytest -q

clean: ## Delete the backend venv, node_modules and the UI build
	rm -rf $(VENV) frontend/node_modules frontend/dist

$(VENV): backend/pyproject.toml backend/uv.lock
	@command -v uv >/dev/null || { echo "error: 'uv' not found. Install it: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
	cd backend && uv sync
	touch $@  # uv sync leaves an up-to-date venv untouched; mark it fresh

$(NODE_MODULES): frontend/package-lock.json
	@command -v npm >/dev/null || { echo "error: 'npm' not found. Install Node.js 18+ (https://nodejs.org)." >&2; exit 1; }
	cd frontend && npm ci

$(DIST): $(NODE_MODULES) $(FRONTEND_SRC)
	cd frontend && npm run build
