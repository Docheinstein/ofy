#!/usr/bin/env bash
# Run Ofy on Android in Termux, as a web app: the server runs in Termux, the UI opens in the browser.
#
#   ./termux.sh setup         install packages, build the backend venv and the UI (slow the first time:
#                             several dependencies are compiled from source)
#   ./termux.sh setup --ui    same, and rebuild the UI even when frontend/dist already exists
#   ./termux.sh               start the server and open http://localhost:8080 in the browser
#   ./termux.sh --port 9000   same, on another port
#
# If the UI won't build on the phone, run `make` on a computer and copy frontend/dist over.
# Environment overrides: OFY_HOST (default 127.0.0.1, phone only; 0.0.0.0 to reach it over Wi-Fi),
# OFY_LIBRARY_DIR (default shared storage Music/Ofy, after `termux-setup-storage`).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$ROOT/backend/.venv"
MODE=run
REBUILD_UI=0
PORT=8080

while [[ $# -gt 0 ]]; do
  case "$1" in
    setup) MODE=setup; shift ;;
    --ui) REBUILD_UI=1; shift ;;
    --port) PORT="$2"; shift 2 ;;
    -h|--help|help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n\033[1;32m==> %s\033[0m\n' "$*"; }

if [[ -z "${TERMUX_VERSION:-}" && ! -d /data/data/com.termux ]]; then
  echo "error: this script is for Termux on Android; use make elsewhere." >&2
  exit 1
fi

setup() {
  step "Termux packages"
  # Runtime: python, ffmpeg, nodejs (yt-dlp's JS runtime for YouTube, and the UI build), rsync/ssh (sync).
  # Build: no prebuilt wheels exist for Termux, so pip compiles pydantic-core (Rust),
  # rapidfuzz (C++/CMake), brotli and pycryptodomex (C).
  pkg install -y python nodejs ffmpeg rsync openssh \
    rust clang cmake ninja binutils pkg-config

  step "Backend: virtualenv"
  # pip rather than uv: uv can't fetch a Python for Android, and pip reliably builds from source here.
  # A venv copied over from another machine doesn't run here: start again.
  "$VENV/bin/python" -c "" 2>/dev/null || { rm -rf "$VENV"; python -m venv "$VENV"; }
  # Only the dependencies are installed; the app runs from backend/src (installing the project itself
  # would mean compiling its build backend, uv_build, from Rust).
  local deps
  mapfile -t deps < <(python -c 'import sys, tomllib; print(*tomllib.load(open(sys.argv[1], "rb"))["project"]["dependencies"], sep="\n")' "$ROOT/backend/pyproject.toml")
  # maturin (pydantic-core's Rust build) needs the Android API level to target
  export ANDROID_API_LEVEL="${ANDROID_API_LEVEL:-$(getprop ro.build.version.sdk)}"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install "${deps[@]}"

  if [[ $REBUILD_UI == 1 || ! -f "$ROOT/frontend/dist/index.html" ]]; then
    step "Frontend: build"
    if ! (cd "$ROOT/frontend" && npm ci && npm run build); then
      echo "warning: the UI didn't build on this device. Run make on a computer and copy" >&2
      echo "         frontend/dist into $ROOT/frontend/dist, then ./termux.sh" >&2
      exit 1
    fi
  else
    echo "frontend/dist exists; pass --ui to rebuild it"
  fi

  if [[ ! -d "$HOME/storage/shared" ]]; then
    echo
    echo "Tip: run termux-setup-storage so the library goes to shared storage (Music/Ofy), where"
    echo "     music players can see it. Without it the library stays inside Termux."
  fi
  step "Done. Start with ./termux.sh"
}

run() {
  "$VENV/bin/python" -c "import fastapi" 2>/dev/null || { echo "error: run ./termux.sh setup first" >&2; exit 1; }
  [[ -f "$ROOT/frontend/dist/index.html" ]] || { echo "error: no UI build in frontend/dist; run ./termux.sh setup" >&2; exit 1; }
  if [[ -z "${OFY_LIBRARY_DIR:-}" && -d "$HOME/storage/shared" ]]; then
    export OFY_LIBRARY_DIR="$HOME/storage/shared/Music/Ofy"
  fi
  export OFY_HOST="${OFY_HOST:-127.0.0.1}" OFY_PORT="$PORT"
  # Keep Android from suspending Termux mid-download while the server runs
  termux-wake-lock 2>/dev/null || true
  trap 'termux-wake-unlock 2>/dev/null || true' EXIT
  local url="http://localhost:$PORT"
  echo "Ofy web UI: $url  (Ctrl-C to stop)"
  (sleep 3 && termux-open-url "$url" 2>/dev/null || true) &
  cd "$ROOT/backend"
  PYTHONPATH="$ROOT/backend/src" "$VENV/bin/python" -m ofy
}

"$MODE"
