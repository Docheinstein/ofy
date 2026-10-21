# Build and run Ofy. `make help` lists the targets.
#
# Targets rebuild only what is out of date: the backend venv when pyproject.toml/uv.lock change,
# node_modules when package-lock.json changes, the UI when any frontend source is newer than the build.
#
# Extra arguments for the desktop app go in ARGS, e.g. `make run ARGS=--debug`; the web server port in
# PORT, e.g. `make web PORT=9000`. `make install` puts an `ofy` command in BINDIR (default ~/.local/bin,
# $PREFIX/bin on Termux) that does `make run` from anywhere.
#
# On Android in Termux (detected automatically) Ofy runs as a web app: `make` also installs the Termux
# packages and builds the venv with pip, and `make run` is the same as `make web`.

SHELL := bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := build

ARGS ?=
PORT ?= 8080

TERMUX := $(if $(or $(TERMUX_VERSION),$(wildcard /data/data/com.termux)),1)
BINDIR ?= $(if $(TERMUX),$(PREFIX)/bin,$(HOME)/.local/bin)

VENV := backend/.venv
NODE_MODULES := frontend/node_modules/.package-lock.json
DIST := frontend/dist/index.html
FRONTEND_SRC := $(shell find frontend/src frontend/public -type f) frontend/index.html \
	frontend/package.json $(wildcard frontend/*.config.*)
TERMUX_PKGS := .termux-packages

.PHONY: help build run web install uninstall test clean

help: ## Show this help
	@awk -F ':.*## ' '/^[a-z]+:.*## / { printf "  make %-9s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

build: $(VENV) $(DIST) ## Install backend + frontend dependencies and build the UI (the default)
	@command -v ffmpeg >/dev/null || echo "warning: ffmpeg not found on PATH; downloads will fail until it is installed." >&2
ifdef TERMUX
	@[[ -d "$$HOME/storage/shared" ]] || echo "tip: run termux-setup-storage so the library goes to shared storage (Music/Ofy), where music players can see it." >&2
endif

run: build ## Desktop app (native window); on Termux the same as make web
ifdef TERMUX
	@$(MAKE) --no-print-directory web
else
	cd backend && uv run ofy-desktop $(ARGS)
endif

web: build ## Web server only: UI at http://localhost:8080 (PORT=... to change)
ifdef TERMUX
	@echo "Ofy web UI: http://localhost:$(PORT)  (Ctrl-C to stop)"
	@# Keep Android from suspending Termux mid-download while the server runs
	termux-wake-lock 2>/dev/null || true; \
	trap 'termux-wake-unlock 2>/dev/null || true' EXIT; \
	(sleep 3 && termux-open-url http://localhost:$(PORT) >/dev/null 2>&1 || true) & \
	if [[ -z "$${OFY_LIBRARY_DIR:-}" && -d "$$HOME/storage/shared" ]]; then \
	  export OFY_LIBRARY_DIR="$$HOME/storage/shared/Music/Ofy"; \
	fi; \
	cd backend && OFY_HOST="$${OFY_HOST:-127.0.0.1}" OFY_PORT=$(PORT) PYTHONPATH=src .venv/bin/python -m ofy
else
	@echo "Ofy web UI: http://localhost:$(PORT)"
	cd backend && OFY_PORT=$(PORT) uv run python -m ofy
endif

# The command is a small script pointing back at this checkout, so it always runs the current code and
# rebuilds whatever is out of date first. Its arguments become ARGS, e.g. `ofy --debug`.
install: build ## Install an `ofy` command in BINDIR (default ~/.local/bin) that does make run from anywhere
	mkdir -p "$(BINDIR)"
	printf '%s\n' '#!/usr/bin/env bash' \
	  '# Installed by `make install` in $(CURDIR): runs `make run` there.' \
	  'args=; (( $$# )) && args=$$(printf "%q " "$$@")' \
	  'exec make --no-print-directory -s -C "$(CURDIR)" run ARGS="$$args"' \
	  > "$(BINDIR)/ofy"
	chmod +x "$(BINDIR)/ofy"
	@echo "Installed $(BINDIR)/ofy"
	@[[ ":$$PATH:" == *":$(BINDIR):"* ]] || echo "warning: $(BINDIR) is not on PATH; add it to run ofy by name." >&2

uninstall: ## Remove the `ofy` command installed by make install
	rm -f "$(BINDIR)/ofy"

test: $(VENV) ## Run the backend unit tests
ifdef TERMUX
	$(VENV)/bin/pip install -q pytest pytest-asyncio
	cd backend && PYTHONPATH=src .venv/bin/python -m pytest -q
else
	cd backend && uv run pytest -q
endif

clean: ## Delete the backend venv, node_modules and the UI build
	rm -rf $(VENV) frontend/node_modules frontend/dist $(TERMUX_PKGS)

ifdef TERMUX
# Runtime: python, ffmpeg, nodejs (yt-dlp's JS runtime for YouTube, and the UI build), rsync/ssh (sync).
# Build: Termux has no prebuilt wheels, so pip compiles pydantic-core (Rust), rapidfuzz (C++/CMake),
# brotli and pycryptodomex (C).
$(TERMUX_PKGS):
	pkg install -y python nodejs ffmpeg rsync openssh rust clang cmake ninja binutils pkg-config
	touch $@

# pip rather than uv: uv can't fetch a Python for Android, and pip reliably builds from source here.
# Only the dependencies are installed; the app runs from backend/src (installing the project itself
# would mean compiling its build backend, uv_build, from Rust). A venv copied over from another machine
# doesn't run here, so it's recreated.
$(VENV): backend/pyproject.toml | $(TERMUX_PKGS)
	$(VENV)/bin/python -c "" 2>/dev/null || { rm -rf $(VENV); python -m venv $(VENV); }
	python -c 'import sys, tomllib; print(*tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"], sep="\n")' \
	  backend/pyproject.toml > $(VENV)/requirements.txt
	$(VENV)/bin/pip install --upgrade pip
	@# maturin (pydantic-core's Rust build) needs the Android API level to target
	ANDROID_API_LEVEL="$${ANDROID_API_LEVEL:-$$(getprop ro.build.version.sdk)}" \
	  $(VENV)/bin/pip install -r $(VENV)/requirements.txt
	touch $@
else
$(VENV): backend/pyproject.toml backend/uv.lock
	@command -v uv >/dev/null || { echo "error: 'uv' not found. Install it: https://docs.astral.sh/uv/getting-started/installation/" >&2; exit 1; }
	cd backend && uv sync
	touch $@  # uv sync leaves an up-to-date venv untouched; mark it fresh
endif

$(NODE_MODULES): frontend/package-lock.json $(if $(TERMUX),| $(TERMUX_PKGS))
	@command -v npm >/dev/null || { echo "error: 'npm' not found. Install Node.js 18+ (https://nodejs.org)." >&2; exit 1; }
	cd frontend && npm ci

ifdef TERMUX
# If the UI won't build on the phone, a frontend/dist built with `make` on a computer and copied over is used.
$(DIST): $(FRONTEND_SRC) | $(TERMUX_PKGS)
	if ! { $(MAKE) --no-print-directory $(NODE_MODULES) && (cd frontend && npm run build); }; then \
	  [[ -f $@ ]] || { echo "error: the UI didn't build on this device. Run make on a computer and copy frontend/dist over." >&2; exit 1; }; \
	  echo "warning: the UI didn't build on this device; using the existing frontend/dist." >&2; \
	  touch $@; \
	fi
else
$(DIST): $(NODE_MODULES) $(FRONTEND_SRC)
	cd frontend && npm run build
endif
