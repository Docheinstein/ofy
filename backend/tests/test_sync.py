import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from ofy import sync
from ofy.config import Settings
from ofy.db import Album, SyncSelection, Track, session


def _album(release_id, artist_id, *tracks):
    with session() as s:
        s.add(Album(release_id=release_id, release_group_id=f"rg-{release_id}", title=release_id, artist="A",
                    artist_id=artist_id))
        for t in tracks:
            s.add(t)
        s.commit()


def _track(track_id, release_id, path=None, status="done"):
    return Track(track_id=track_id, recording_id=f"rec-{track_id}", release_id=release_id,
                 release_group_id=f"rg-{release_id}", status=status, file_path=str(path) if path else None)


def _select(kind, ref_id, on=True):
    with session() as s:
        row = s.get(SyncSelection, (kind, ref_id))
        if on and row is None:
            s.add(SyncSelection(kind=kind, ref_id=ref_id))
        elif not on and row is not None:
            s.delete(row)
        s.commit()


@pytest.fixture
def library(tmp_db, tmp_path):
    lib = tmp_path / "lib"
    files = {}
    for rel in ["PF/Meddle/PF - Echoes.mp3", "PF/Meddle/PF - One of These Days.mp3", "PF/The Wall/PF - Hey You.mp3",
                "FM/Rumours/FM - Dreams.mp3"]:
        p = lib / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 10)
        files[p.stem.split(" - ")[1]] = p
    files["Echoes"].with_suffix(".lrc").write_text("[00:01.00] lyrics")
    outside = tmp_path / "elsewhere.mp3"
    outside.write_bytes(b"y")
    _album("meddle", "pf", _track("echoes", "meddle", files["Echoes"]), _track("otd", "meddle", files["One of These Days"]))
    _album("wall", "pf", _track("heyyou", "wall", files["Hey You"]), _track("comfortably", "wall", status="none"))
    _album("rumours", "fm", _track("dreams", "rumours", files["Dreams"]), _track("odd", "rumours", outside))
    return lib


def _rels(plan):
    return sorted(str(r) for r, _ in plan.files)


def test_selection_covers_children(library):
    assert sync.build_plan(library).files == []
    _select("track", "dreams")
    assert _rels(sync.build_plan(library)) == ["FM/Rumours/FM - Dreams.mp3"]
    _select("album", "meddle")
    assert _rels(sync.build_plan(library)) == [
        "FM/Rumours/FM - Dreams.mp3", "PF/Meddle/PF - Echoes.lrc", "PF/Meddle/PF - Echoes.mp3",
        "PF/Meddle/PF - One of These Days.mp3"]
    _select("artist", "pf")
    plan = sync.build_plan(library)
    assert "PF/The Wall/PF - Hey You.mp3" in _rels(plan)
    assert plan.tracks == 4
    assert plan.pending == 1  # "comfortably" is selected (via the artist) but not downloaded
    _select("artist", "fm")
    assert sync.build_plan(library).outside == 1  # a file outside the library folder is skipped


def test_library_albums_list_downloaded_tracks(library):
    from ofy.api.actions import library_albums

    tracks = {a["release_id"]: [t["track_id"] for t in a["tracks"]] for a in library_albums()}
    assert tracks == {"meddle": ["echoes", "otd"], "wall": ["heyyou"], "rumours": ["dreams", "odd"]}


def test_rsync_command_over_ssh(tmp_path):
    s = Settings(sync_host="nas.local", sync_user="me", sync_port=2222, sync_path="~/Music/Ofy", sync_ssh_key="/k/id")
    cmd = sync.rsync_command(s, tmp_path, dry_run=True)
    assert cmd[0] == "rsync" and "--delete" in cmd and "--dry-run" in cmd and "--copy-links" in cmd
    ssh = cmd[cmd.index("-e") + 1]
    assert "-p 2222" in ssh and "-i /k/id" in ssh and "BatchMode=yes" in ssh
    assert cmd[-2:] == [f"{tmp_path}/", "me@nas.local:Music/Ofy/"]
    s = Settings(sync_host="fe80::1", sync_path="/srv/music/", sync_delete=False)
    cmd = sync.rsync_command(s, tmp_path, dry_run=False)
    assert "--delete" not in cmd and "--dry-run" not in cmd and "-e" in cmd
    assert cmd[-1] == "[fe80::1]:/srv/music/"
    with pytest.raises(sync.SyncError):
        sync.rsync_command(Settings(sync_host="nas"), tmp_path, dry_run=False)


def test_password_login_goes_through_askpass(tmp_path, monkeypatch):
    import subprocess

    monkeypatch.setattr(sync, "env", SimpleNamespace(data_dir=tmp_path / "data"))
    s = Settings(sync_host="nas.local", sync_path="Music", sync_password="s3cr'et $x")
    ssh = sync.rsync_command(s, tmp_path, dry_run=False)[-3]
    assert "BatchMode" not in ssh and "NumberOfPasswordPrompts=1" in ssh
    extra = sync.ssh_env(s)
    assert extra["SSH_ASKPASS_REQUIRE"] == "force" and "s3cr" not in Path(extra["SSH_ASKPASS"]).read_text()
    out = subprocess.run([extra["SSH_ASKPASS"], "Password:"], env=extra, capture_output=True, text=True, check=True)
    assert out.stdout == "s3cr'et $x\n"
    assert sync.ssh_env(Settings(sync_host="nas.local")) == {}
    assert sync.ssh_env(Settings(sync_password="x")) == {}  # local folder: no ssh


def test_explain_permission_denied():
    keys_only = "me@nas: Permission denied (publickey)."
    both = "me@nas: Permission denied (publickey,password)."
    assert "ssh-copy-id" in sync._explain(keys_only, Settings(sync_password="x"))
    assert "check the user and password" in sync._explain(both, Settings(sync_password="x"))
    assert "set the password" in sync._explain(both, Settings())


def test_api_never_returns_the_password(tmp_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ofy.api import settings as settings_api
    from ofy.config import PASSWORD_MASK
    from ofy.db import load_settings

    app = FastAPI()
    app.include_router(settings_api.router)
    with TestClient(app) as c:
        assert c.get("/api/settings").json()["sync_password"] == ""
        body = {**c.get("/api/settings").json(), "sync_password": "hunter2"}
        assert c.put("/api/settings", json=body).json()["sync_password"] == PASSWORD_MASK
        got = c.get("/api/settings").json()
        assert got["sync_password"] == PASSWORD_MASK
        c.put("/api/settings", json={**got, "concurrency": 3})  # the mask round-trips: password kept
        assert load_settings().sync_password == "hunter2" and load_settings().concurrency == 3
        c.put("/api/settings", json={**got, "sync_password": ""})
        assert load_settings().sync_password == ""


def test_parse_rsync_output():
    sync.state = sync.SyncState()
    for line in ["<f+++++++++ PF/Meddle/PF - Echoes.mp3", "cd+++++++++ PF/", "*deleting   Old/song.mp3", "*deleting   Old/",
                 "     12,345,678  42%   10.50MB/s    0:00:07 (xfr#1, to-chk=3/9)"]:
        sync.parse_line(line)
    assert sync.state.transferred == 1 and sync.state.deleted == 1 and sync.state.percent == 42
    assert sync.state.speed == "10.50MB/s"
    assert sync.state.changes == ["+ PF/Meddle/PF - Echoes.mp3", "- Old/song.mp3"]


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
async def test_sync_to_local_folder_mirrors_selection(library, tmp_path, monkeypatch):
    monkeypatch.setattr(sync, "env", SimpleNamespace(data_dir=tmp_path / "data"))
    dest = tmp_path / "remote"
    settings = Settings(library_path=str(library), sync_path=str(dest))

    async def run(dry_run=False):
        sync.start(settings, dry_run)
        await sync._task
        assert sync.state.ok, sync.state.error
        return sync.state

    _select("album", "meddle")
    _select("track", "dreams")
    st = await run(dry_run=True)
    assert st.transferred == 4 and st.dry_run and not any(dest.iterdir())
    st = await run()
    assert st.transferred == 4
    assert sorted(str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()) == [
        "FM/Rumours/FM - Dreams.mp3", "PF/Meddle/PF - Echoes.lrc", "PF/Meddle/PF - Echoes.mp3",
        "PF/Meddle/PF - One of These Days.mp3"]
    assert not (dest / "PF/Meddle/PF - Echoes.mp3").is_symlink()
    assert (await run()).transferred == 0  # nothing changed

    _select("album", "meddle", on=False)
    st = await run()
    assert st.deleted == 3  # files only, not the emptied folder
    assert [str(p.relative_to(dest)) for p in dest.rglob("*") if p.is_file()] == ["FM/Rumours/FM - Dreams.mp3"]

    _select("track", "dreams", on=False)
    sync.start(settings, False)
    await sync._task
    assert sync.state.ok is False and "empty the destination" in sync.state.error
    assert (dest / "FM/Rumours/FM - Dreams.mp3").is_file()


@pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")
def test_api_selection_and_run(library, tmp_path, monkeypatch):
    """Through HTTP: the run starts on the server's event loop (not a worker thread) and finishes."""
    import time

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ofy.api import sync as sync_api
    from ofy.db import save_settings

    monkeypatch.setattr(sync, "env", SimpleNamespace(data_dir=tmp_path / "data"))
    dest = tmp_path / "remote"
    save_settings(Settings(library_path=str(library), sync_path=str(dest)))
    app = FastAPI()
    app.include_router(sync_api.router)
    with TestClient(app) as c:
        r = c.put("/api/sync/selection", json={"kind": "album", "id": "meddle", "selected": True, "title": "Meddle"})
        assert r.status_code == 200
        assert [i["ref_id"] for i in c.get("/api/sync/selection").json()] == ["meddle"]
        assert c.get("/api/sync/summary").json()["files"] == 3
        assert c.post("/api/sync/test").json()["ok"]
        assert c.post("/api/sync/run", json={}).json()["running"]
        for _ in range(100):
            st = c.get("/api/sync/status").json()
            if not st["running"]:
                break
            time.sleep(0.05)
        assert st["ok"], st["error"]
        assert st["transferred"] == 3 and (dest / "PF/Meddle/PF - Echoes.mp3").is_file()
