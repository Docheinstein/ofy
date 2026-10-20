"""Desktop app: runs the backend in a background thread and shows the UI in a native window (pywebview).

    uv run ofy-desktop [--port 0] [--gui gtk|qt] [--debug] [--selftest]

Closing the window stops the backend. If an Ofy backend is already running for the same data
directory (another window, or ``python -m ofy``), the window attaches to it instead of starting a
second one, so two job queues never share a database.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

log = logging.getLogger("ofy.desktop")

SYSTEM_SITE_DIRS = (
    "/usr/lib/python3/dist-packages",  # Debian/Ubuntu
    f"/usr/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages",  # Arch, Fedora
    f"/usr/lib64/python{sys.version_info.major}.{sys.version_info.minor}/site-packages",  # Fedora (arch-specific)
)


# --- helpers (pure / easily testable) -----------------------------------------------------------

def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
        return True


def pick_port(preferred: int, host: str = "127.0.0.1") -> int:
    """``preferred`` if free (stable origin keeps the UI's local settings), else an ephemeral port."""
    if preferred and port_is_free(preferred, host):
        return preferred
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((host, 0))
        return s.getsockname()[1]


def health(url: str, timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"{url}/api/health", timeout=timeout) as r:
            data = json.load(r)
            return data if data.get("ok") else None
    except (OSError, ValueError):
        return None


def is_ofy(url: str, timeout: float = 1.0) -> bool:
    return health(url, timeout) is not None


def serves_data_dir(url: str, data_dir: Path) -> bool:
    h = health(url)
    return bool(h) and Path(h.get("data_dir", "")).resolve() == data_dir.resolve()


def wait_until_ready(url: str, timeout: float, alive=lambda: True) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_ofy(url, timeout=0.5):
            return True
        if not alive():
            return False
        time.sleep(0.15)
    return False


def instance_file(data_dir: Path) -> Path:
    return data_dir / "desktop-instance.json"


def running_instance(data_dir: Path, preferred_port: int | None = None) -> str | None:
    """URL of a live backend using this data directory: the one recorded by a previous desktop
    launch, or a plain ``python -m ofy`` server on the preferred port."""
    candidates = []
    try:
        candidates.append(json.loads(instance_file(data_dir).read_text())["url"])
    except (OSError, ValueError, KeyError):
        pass
    if preferred_port:
        candidates.append(f"http://127.0.0.1:{preferred_port}")
    for url in candidates:
        if serves_data_dir(url, data_dir):
            return url
    return None


def ensure_gtk_bindings(link_dir: Path) -> bool:
    """Make PyGObject (``gi``) importable inside the virtualenv.

    PyGObject ships no wheels and building it needs system dev headers, so we reuse the distro's
    ``python3-gi`` — but only ``gi``/``cairo``/``pygtkcompat`` (via symlinks), never the whole system
    site-packages, so nothing else can shadow the venv's dependencies.
    """
    try:
        import gi  # noqa: F401

        return True
    except ImportError:
        pass
    for site in SYSTEM_SITE_DIRS:
        root = Path(site)
        if not (root / "gi" / "__init__.py").is_file():
            continue
        abi = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
        if not any(abi in p.name for p in (root / "gi").glob("_gi*.so")):
            continue  # built for another Python version
        link_dir.mkdir(parents=True, exist_ok=True)
        for name in ("gi", "cairo", "pygtkcompat"):
            src, dst = root / name, link_dir / name
            if src.exists() and not dst.exists():
                dst.symlink_to(src)
        if str(link_dir) not in sys.path:
            sys.path.append(str(link_dir))
        try:
            import gi  # noqa: F401,F811

            return True
        except ImportError:
            continue
    return False


def desktop_entry(exec_path: str, icon: Path) -> str:
    """freedesktop.org launcher so Ofy shows up in the app menu / dock."""
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Ofy\n"
        "Comment=Browse MusicBrainz, download and tag music for offline listening\n"
        f"Exec={exec_path}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=AudioVideo;Audio;Player;\n"
        "StartupWMClass=Ofy\n"
    )


def install_shortcut() -> Path:
    from ofy.config import env

    apps = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    script = Path(sys.argv[0]).resolve()
    exec_path = str(script) if script.name == "ofy-desktop" else f"{sys.executable} -m ofy.desktop"
    target = apps / "ofy.desktop"
    target.write_text(desktop_entry(exec_path, env.static_dir / "favicon.svg"))
    target.chmod(0o755)
    return target


# --- self test ------------------------------------------------------------------------------------

SELFTEST_JS = """
window.__ofy_selftest = null;
(async () => {
  const a = document.createElement('audio');
  const health = await fetch('/api/health').then(r => r.json()).catch(e => ({error: String(e)}));
  return {
    title: document.title,
    rendered: !!document.querySelector('#root aside nav'),
    health,
    codecs: {
      mp3: a.canPlayType('audio/mpeg'),
      aac: a.canPlayType('audio/mp4; codecs="mp4a.40.2"'),
      opus_ogg: a.canPlayType('audio/ogg; codecs="opus"'),
      opus_webm: a.canPlayType('audio/webm; codecs="opus"'),
    },
  };
})().then(r => { window.__ofy_selftest = JSON.stringify(r); },
          e => { window.__ofy_selftest = JSON.stringify({error: String(e)}); });
"""

PLAY_JS = """
window.__ofy_selftest = null;
(async () => {
  const a = new Audio('%s');
  a.muted = true;
  try { await a.play(); } catch (e) { return {error: String(e)}; }
  await new Promise(r => setTimeout(r, 4000));
  const out = {currentTime: a.currentTime, paused: a.paused, error: a.error && a.error.code};
  a.pause();
  return out;
})().then(r => { window.__ofy_selftest = JSON.stringify(r); },
          e => { window.__ofy_selftest = JSON.stringify({error: String(e)}); });
"""


def _run_async_js(window, script: str, timeout: float) -> dict:
    """evaluate_js doesn't await promises on every backend: start the work, then poll for the result."""
    window.evaluate_js(script)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        raw = window.evaluate_js("window.__ofy_selftest")
        if raw:
            return json.loads(raw)
        time.sleep(0.25)
    return {"error": "timeout"}


def _selftest(window, play: list[str], result: dict) -> None:
    try:
        deadline = time.monotonic() + 30
        info: dict = {}
        while time.monotonic() < deadline:
            try:
                info = _run_async_js(window, SELFTEST_JS, 10)
                if info.get("rendered"):
                    break
            except Exception as e:  # page not ready yet
                info = {"error": repr(e)}
            time.sleep(0.5)
        result["page"] = info
        result["playback"] = {path: _run_async_js(window, PLAY_JS % path, 60) for path in play}
    except Exception as e:
        result["error"] = repr(e)
    finally:
        window.destroy()


# --- main -----------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ofy-desktop", description="Ofy desktop window")
    p.add_argument("--port", type=int, default=int(os.environ.get("OFY_PORT", "8080")),
                   help="preferred backend port (falls back to a free one); 0 = always pick a free port")
    p.add_argument("--gui", choices=["gtk", "qt"], default=None, help="force a pywebview backend")
    p.add_argument("--debug", action="store_true", help="enable the webview inspector")
    p.add_argument("--selftest", action="store_true", help="open, check the UI renders, print a report, exit")
    p.add_argument("--play", action="append", default=[], metavar="PATH",
                   help="with --selftest: also try playing this URL path (e.g. /api/stream/<recording-id>)")
    p.add_argument("--install-shortcut", action="store_true",
                   help="add Ofy to the desktop app menu (Linux, freedesktop.org) and exit")
    args = p.parse_args(argv)
    if args.install_shortcut:
        print(f"Installed {install_shortcut()}")
        return 0

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # The desktop backend only listens locally. Must be set before ofy.config is imported.
    os.environ.setdefault("OFY_HOST", "127.0.0.1")

    from ofy.config import env, migrate_legacy_data_dir

    if migrate_legacy_data_dir():
        log.info("moved data from the app's former name to %s", env.data_dir)
    env.data_dir.mkdir(parents=True, exist_ok=True)
    gui = args.gui
    if gui in (None, "gtk") and sys.platform.startswith("linux"):
        if ensure_gtk_bindings(env.data_dir / "gtk-bindings"):
            gui = gui or "gtk"
            # WebKitGTK's DMA-BUF renderer crashes the window on NVIDIA under Wayland ("Error 71
            # (Protocol error) dispatching to Wayland display"); the fallback is barely slower.
            os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
        elif gui == "gtk":
            print("GTK bindings not found: install python3-gi and gir1.2-webkit2-4.1 "
                  "(or use --gui qt after `uv sync --extra qt`)", file=sys.stderr)
            return 2

    import webview

    if not (env.static_dir / "index.html").is_file():
        print(f"Frontend not built ({env.static_dir}). Run: cd frontend && npm install && npm run build",
              file=sys.stderr)
        return 2

    server = thread = None
    url = running_instance(env.data_dir, args.port)
    if url:
        log.info("attaching to running backend at %s", url)
    else:
        import uvicorn

        port = pick_port(args.port, env.host)
        url = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config("ofy.main:app", host=env.host, port=port, log_level="info"))
        thread = threading.Thread(target=server.run, name="ofy-backend", daemon=True)
        thread.start()
        if not wait_until_ready(url, timeout=30, alive=thread.is_alive):
            print("backend failed to start; see log above", file=sys.stderr)
            return 1
        instance_file(env.data_dir).write_text(json.dumps({"url": url, "pid": os.getpid()}))
        log.info("backend running at %s", url)

    window = webview.create_window(
        "Ofy", url, width=1440, height=920, min_size=(900, 600), background_color="#000000",
    )
    result: dict = {}
    try:
        webview.start(
            _selftest if args.selftest else None,
            (window, args.play, result) if args.selftest else None,
            gui=gui, debug=args.debug, private_mode=False, storage_path=str(env.data_dir / "webview"),
        )
    finally:
        if server is not None:
            log.info("window closed, stopping backend")
            server.should_exit = True
            thread.join(timeout=15)  # type: ignore[union-attr]
            try:
                if json.loads(instance_file(env.data_dir).read_text()).get("url") == url:
                    instance_file(env.data_dir).unlink()
            except (OSError, ValueError):
                pass
    if args.selftest:
        print(json.dumps({"url": url, "gui": gui, **result}, indent=2))
        page = result.get("page") or {}
        ok = page.get("rendered") and (page.get("health") or {}).get("ok")
        ok = ok and all((r or {}).get("currentTime", 0) > 1 for r in result.get("playback", {}).values())
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
