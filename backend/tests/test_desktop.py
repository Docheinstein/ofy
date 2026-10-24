import json
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from ofy import desktop
from ofy.config import default_data_dir, default_library_dir, default_static_dir


def test_pick_port_prefers_free_port():
    free = desktop.pick_port(0)
    assert desktop.pick_port(free) == free


def test_pick_port_falls_back_when_taken():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen()
        taken = s.getsockname()[1]
        assert not desktop.port_is_free(taken)
        assert desktop.pick_port(taken) != taken


@pytest.fixture
def fake_backend(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"ok": True, "version": "x", "data_dir": str(data_dir)}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], data_dir
    srv.shutdown()


def test_running_instance_from_instance_file(fake_backend):
    port, data_dir = fake_backend
    url = f"http://127.0.0.1:{port}"
    assert desktop.running_instance(data_dir) is None
    desktop.instance_file(data_dir).write_text(json.dumps({"url": url}))
    assert desktop.running_instance(data_dir) == url


def test_running_instance_on_preferred_port(fake_backend):
    port, data_dir = fake_backend
    assert desktop.running_instance(data_dir, port) == f"http://127.0.0.1:{port}"


def test_other_data_dir_is_not_attached(fake_backend, tmp_path):
    port, _ = fake_backend
    assert desktop.running_instance(tmp_path / "other", port) is None


def test_stale_instance_file_ignored(tmp_path):
    desktop.instance_file(tmp_path).write_text(json.dumps({"url": "http://127.0.0.1:9"}))
    assert desktop.running_instance(tmp_path) is None


def test_wait_until_ready_stops_when_thread_dies():
    assert desktop.wait_until_ready("http://127.0.0.1:9", timeout=5, alive=lambda: False) is False


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux GTK bindings")
def test_gtk_bindings_link_only_gi(tmp_path, monkeypatch):
    site = tmp_path / "site"
    gi = site / "gi"
    gi.mkdir(parents=True)
    abi = f"cpython-{sys.version_info.major}{sys.version_info.minor}"
    (gi / "__init__.py").write_text("FAKE = True\n")
    (gi / f"_gi.{abi}-x86_64-linux-gnu.so").write_bytes(b"")
    (site / "requests").mkdir()  # must NOT become importable
    monkeypatch.setattr(desktop, "SYSTEM_SITE_DIRS", (str(site),))
    monkeypatch.setitem(sys.modules, "gi", None)  # pretend gi isn't installed in the venv
    links = tmp_path / "links"
    monkeypatch.setattr(sys, "path", list(sys.path))

    import builtins

    real_import = builtins.__import__
    state = {"linked": False}

    def fake_import(name, *a, **k):
        if name == "gi":
            if not state["linked"]:
                raise ImportError
            return type(sys)("gi")
        return real_import(name, *a, **k)

    def mark(*a, **k):
        state["linked"] = True
        return orig_symlink(*a, **k)

    orig_symlink = Path.symlink_to
    monkeypatch.setattr(Path, "symlink_to", mark)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert desktop.ensure_gtk_bindings(links) is True
    assert (links / "gi").is_symlink() and not (links / "requests").exists()
    assert str(links) in sys.path


def test_defaults_are_absolute_and_cwd_independent():
    assert default_data_dir().is_absolute() and default_data_dir().name.lower() == "ofy"
    assert default_library_dir() == Path.home() / "Music" / "Ofy"
    assert default_static_dir().parts[-2:] == ("frontend", "dist")


def test_desktop_entry():
    e = desktop.desktop_entry("/x/ofy-desktop", Path("/x/favicon.svg"))
    assert e.startswith("[Desktop Entry]\n") and "Exec=/x/ofy-desktop\n" in e and "Terminal=false" in e


def test_icons_exist():
    assert desktop.window_icon().is_file()
    assert (desktop.ASSETS / "icon.png").is_file() and (desktop.ASSETS / "icon.ico").is_file()


def test_ensure_shortcut_adds_launcher_and_keeps_its_command(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    target = tmp_path / "applications" / "ofy.desktop"
    desktop.ensure_shortcut()
    assert f"Icon={desktop.ASSETS / 'icon.png'}\n" in target.read_text()
    # a launcher from make install (or an older version, with the old icon) keeps what it runs
    target.write_text(desktop.desktop_entry("/home/u/.local/bin/ofy", Path("/x/favicon.svg")))
    desktop.ensure_shortcut()
    e = target.read_text()
    assert "Exec=/home/u/.local/bin/ofy\n" in e and f"Icon={desktop.ASSETS / 'icon.png'}\n" in e


def test_migrate_legacy_data_dir(tmp_path, monkeypatch):
    from ofy import config

    monkeypatch.delenv("OFY_DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    old = tmp_path / "offliner"
    old.mkdir()
    (old / "offliner.db").write_text("db")
    (old / "offliner.db-wal").write_text("wal")
    (old / "covers").mkdir()
    (old / "webview" / "cache").mkdir(parents=True)
    (old / "webview" / "localstorage").mkdir()
    assert config.migrate_legacy_data_dir() == tmp_path / "ofy"
    new = tmp_path / "ofy"
    assert not old.exists()
    assert (new / "ofy.db").read_text() == "db" and (new / "ofy.db-wal").exists() and (new / "covers").is_dir()
    assert not (new / "webview" / "cache").exists() and (new / "webview" / "localstorage").is_dir()
    assert config.migrate_legacy_data_dir() is None  # one-time


def test_migration_skipped_while_old_instance_runs(tmp_path, monkeypatch):
    from ofy import config

    monkeypatch.delenv("OFY_DATA_DIR", raising=False)
    monkeypatch.setattr(config.sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    (tmp_path / "offliner").mkdir()
    (tmp_path / "offliner" / "desktop-instance.json").write_text("{}")
    assert config.migrate_legacy_data_dir() is None
    assert (tmp_path / "offliner").exists()


def test_spa_cache_headers(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ofy.main import _mount_spa

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<title>Ofy</title>")
    (tmp_path / "assets" / "index-abc123.js").write_text("x")
    app = FastAPI()
    _mount_spa(app, tmp_path)
    c = TestClient(app)
    assert c.get("/").headers["cache-control"] == "no-cache"
    assert c.get("/library").headers["cache-control"] == "no-cache"
    assert "immutable" in c.get("/assets/index-abc123.js").headers["cache-control"]
    assert c.get("/api/nope").status_code == 404
