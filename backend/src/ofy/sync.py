"""Sync the selected part of the library to a remote peer with rsync.

The selection (artists, albums, tracks; see ``SyncSelection``) resolves to the downloaded files below
it plus their lyrics sidecars. Those are mirrored as symlinks into a staging tree inside the data
directory, which rsync then copies (``--copy-links``) to the remote over SSH, or to a local folder
when no host is set. With ``sync_delete`` the remote ends up holding exactly the selection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shlex
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from sqlmodel import select

from ofy.config import Settings, env
from ofy.db import Album, SyncSelection, Track, session
from ofy.download.paths import artist_key
from ofy.events import hub
from ofy.library.scanner import AUDIO_EXTS

log = logging.getLogger(__name__)

SIDECARS = (".lrc",)
MAX_LISTED = 500  # changed paths kept for display per run


class SyncError(Exception):
    pass


# --- selection -> files -----------------------------------------------------------------------

@dataclass
class Plan:
    files: list[tuple[Path, Path]] = field(default_factory=list)  # (path relative to library, absolute)
    bytes: int = 0
    tracks: int = 0
    pending: int = 0  # selected tracks not downloaded (yet)
    outside: int = 0  # downloaded outside the library folder: not synced


def selected_tracks() -> list[Track]:
    with session() as s:
        sel = list(s.exec(select(SyncSelection)).all())
        if not sel:
            return []
        ids = {k: {x.ref_id for x in sel if x.kind == k} for k in ("artist", "album", "track")}
        album_artist = {a.release_id: a.artist_id for a in s.exec(select(Album)).all()}
        tracks = list(s.exec(select(Track)).all())
    return [
        t for t in tracks
        if t.track_id in ids["track"] or t.release_id in ids["album"] or album_artist.get(t.release_id) in ids["artist"]
    ]


def build_plan(root: Path) -> Plan:
    plan = Plan()
    root = root.expanduser().resolve()
    for t in selected_tracks():
        audio = Path(t.file_path) if t.status == "done" and t.file_path else None
        if audio is None or not audio.is_file():
            plan.pending += 1
            continue
        try:
            rel = audio.resolve().relative_to(root)
        except ValueError:
            plan.outside += 1
            continue
        plan.tracks += 1
        for p in [audio, *(audio.with_suffix(e) for e in SIDECARS)]:
            if p.is_file():
                plan.files.append((rel.with_name(p.name), p))
                plan.bytes += p.stat().st_size
    return plan



# --- selection <-> list file ------------------------------------------------------------------
# A list of paths relative to the library, one per line (what rsync's --files-from reads): an
# artist's folder, an album's folder or a song's file.

@dataclass
class _Library:
    """Where the downloaded songs are, relative to the library folder."""

    tracks: dict[str, Track]  # "Artist/Album/Song.mp3" -> its track
    albums: dict[str, list[Album]]  # "Artist/Album" -> the albums with songs in it
    artist_ids: dict[str, set[str]]  # "Artist" -> the album artists with songs in it
    artist_folders: dict[str, set[str]]  # album artist id -> the folders their songs are in


def _library(root: Path) -> _Library:
    root = root.expanduser().resolve()
    with session() as s:
        albums = {a.release_id: a for a in s.exec(select(Album)).all()}
        done = list(s.exec(select(Track).where(Track.status == "done")).all())
    lib = _Library({}, {}, {}, {})
    for t in done:
        try:
            rel = PurePosixPath(Path(t.file_path or "").resolve().relative_to(root).as_posix())
        except ValueError:
            continue
        a = albums.get(t.release_id)
        lib.tracks[str(rel)] = t
        if a is None or len(rel.parts) < 2:
            continue
        in_folder = lib.albums.setdefault(str(rel.parent), [])
        if a not in in_folder:
            in_folder.append(a)
        if a.artist_id:
            lib.artist_ids.setdefault(rel.parts[0], set()).add(a.artist_id)
            lib.artist_folders.setdefault(a.artist_id, set()).add(rel.parts[0])
    return lib


def export_list(root: Path) -> str:
    """The selection as a list file."""
    lib = _library(root)
    album_folders: dict[str, set[str]] = {}
    for folder, albums in lib.albums.items():
        for a in albums:
            album_folders.setdefault(a.release_id, set()).add(folder)
    track_paths = {t.track_id: rel for rel, t in lib.tracks.items()}
    with session() as s:
        sel = list(s.exec(select(SyncSelection)).all())
    lines: set[str] = set()
    for x in sel:
        if x.kind == "artist":
            lines |= lib.artist_folders.get(x.ref_id, set())
        elif x.kind == "album":
            lines |= album_folders.get(x.ref_id, set())
        elif x.ref_id in track_paths:
            lines.add(track_paths[x.ref_id])
    return "".join(f"{line}\n" for line in sorted(lines, key=str.casefold))


def _loose(rel: str) -> tuple[str, ...]:
    """A path compared leniently: each part as artist_key sees it, a song without its extension."""
    p = PurePosixPath(rel)
    parts = (*p.parts[:-1], p.stem) if p.suffix.lower() in AUDIO_EXTS else p.parts
    return tuple(artist_key(x) for x in parts)


@dataclass
class ListImport:
    selection: list[SyncSelection] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)


def import_list(text: str, root: Path) -> ListImport:
    """What a list file selects. A line matches its path, or failing that the one path that differs
    only in case, punctuation, accents, "The" or "&"/"and"; one that matches nothing, or more than
    one path, is left out (in ``unmatched``). An artist's folder selects the artist when all their
    songs are in folders the list names, otherwise the albums in that folder."""
    lib = _library(root)
    known = {"track": set(lib.tracks), "album": set(lib.albums), "artist": set(lib.artist_ids)}
    loose: dict[tuple[str, ...], set[tuple[str, str]]] = {}
    for kind, paths in known.items():
        for rel in paths:
            loose.setdefault(_loose(rel), set()).add((kind, rel))
    found: dict[str, set[str]] = {"artist": set(), "album": set(), "track": set()}
    out = ListImport()
    for raw in text.splitlines():
        line = raw.strip().strip("/")
        if not line or line.startswith("#") or PurePosixPath(line).suffix.lower() in SIDECARS:
            continue
        kind = ("track" if PurePosixPath(line).suffix.lower() in AUDIO_EXTS
                else "artist" if len(PurePosixPath(line).parts) == 1 else "album")
        if line in known[kind]:
            found[kind].add(line)
            continue
        hits = {rel for k, rel in loose.get(_loose(line), set()) if k == kind}
        if len(hits) == 1:
            found[kind] |= hits
        else:
            out.unmatched.append(line)

    picked: dict[tuple[str, str], tuple[str, str]] = {}  # (kind, id) -> (title, subtitle)
    for folder in sorted(found["artist"]):
        for artist_id in sorted(lib.artist_ids[folder]):
            if lib.artist_folders[artist_id] <= found["artist"]:
                name = next(a.artist for albums in lib.albums.values() for a in albums if a.artist_id == artist_id)
                picked[("artist", artist_id)] = (name, "Artist")
        for rel, albums in lib.albums.items():
            if PurePosixPath(rel).parts[0] == folder:
                for a in albums:
                    if not a.artist_id or not lib.artist_folders[a.artist_id] <= found["artist"]:
                        picked[("album", a.release_id)] = (a.title, a.artist)
    for rel in found["album"]:
        for a in lib.albums[rel]:
            picked[("album", a.release_id)] = (a.title, a.artist)
    for rel in found["track"]:
        t = lib.tracks[rel]
        picked[("track", t.track_id)] = (t.title, t.artist)
    out.selection = [SyncSelection(kind=k, ref_id=i, title=title, subtitle=sub)
                     for (k, i), (title, sub) in sorted(picked.items())]
    return out

def stage(plan: Plan, stage_dir: Path) -> None:
    """Recreate ``stage_dir`` as a tree of symlinks to the planned files."""
    shutil.rmtree(stage_dir, ignore_errors=True)
    stage_dir.mkdir(parents=True)
    for rel, src in plan.files:
        link = stage_dir / rel
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(src)


# --- rsync / ssh commands ---------------------------------------------------------------------

def _remote_path(settings: Settings) -> str:
    path = settings.sync_path.strip()
    if not path:
        raise SyncError("Set the destination folder first")
    if settings.sync_host.strip():
        # SSH sessions start in the home directory, so "~/Music" is just "Music".
        if path == "~":
            return "."
        return path[2:] if path.startswith("~/") else path
    return str(Path(path).expanduser())


def _target(settings: Settings) -> str:
    host = settings.sync_host.strip()
    user = settings.sync_user.strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6
    return f"{user}@{host}" if user else host


def ssh_command(settings: Settings) -> list[str]:
    # Without a password nothing can answer a prompt: BatchMode fails at once instead of waiting.
    auth = ["NumberOfPasswordPrompts=1"] if settings.sync_password else ["BatchMode=yes"]
    cmd = ["ssh", "-p", str(settings.sync_port), "-o", auth[0], "-o", "ConnectTimeout=10",
           "-o", "StrictHostKeyChecking=accept-new"]
    if settings.sync_ssh_key.strip():
        cmd += ["-i", str(Path(settings.sync_ssh_key.strip()).expanduser())]
    return cmd


ASKPASS = '#!{sh}\nprintf \'%s\\n\' "$OFY_SSH_PASSWORD"\n'


def ssh_env(settings: Settings) -> dict[str, str]:
    """Environment for ssh (and rsync's ssh): with a password, ssh asks SSH_ASKPASS for it.

    ssh only reads passwords from a terminal, which the app doesn't have; SSH_ASKPASS_REQUIRE=force
    (OpenSSH 8.4+) makes it run the helper instead, which prints the password passed in the
    environment, so the password never lands on disk or on a command line.
    """
    if not settings.sync_password or not settings.sync_host.strip():
        return {}
    helper = env.data_dir / "sync" / "askpass"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text(ASKPASS.format(sh=shutil.which("sh") or "/bin/sh"))
    helper.chmod(0o700)
    return {"SSH_ASKPASS": str(helper), "SSH_ASKPASS_REQUIRE": "force", "OFY_SSH_PASSWORD": settings.sync_password}


def rsync_command(settings: Settings, source: Path, dry_run: bool) -> list[str]:
    path = _remote_path(settings).rstrip("/") or "/"
    cmd = [
        "rsync", "--recursive", "--times", "--copy-links", "--modify-window=2", "--partial",
        "--no-inc-recursive", "--itemize-changes", "--info=progress2", "--protect-args",
    ]
    if settings.sync_delete:
        cmd.append("--delete")
    if dry_run:
        cmd.append("--dry-run")
    if settings.sync_host.strip():
        cmd += ["-e", shlex.join(ssh_command(settings))]
        dest = f"{_target(settings)}:{path}/"
    else:
        dest = f"{path}/"
    return [*cmd, f"{source}/", dest]


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        raise SyncError(f"'{tool}' is not installed on this computer")


def _explain(stderr: str, settings: Settings) -> str:
    msg = stderr.strip().splitlines()[-1] if stderr.strip() else "failed"
    if "Permission denied (" in stderr:
        methods = stderr.split("Permission denied (", 1)[1].split(")", 1)[0]
        if "password" not in methods and "keyboard-interactive" not in methods:
            msg += " — the remote only accepts SSH keys (set one up with: ssh-copy-id user@host)"
        elif settings.sync_password:
            msg += " — check the user and password"
        else:
            msg += " — set the password, or set up SSH key login (ssh-copy-id user@host)"
    elif "SSH_ASKPASS" in stderr or "can't open /dev/tty" in stderr:
        msg += " — password login needs OpenSSH 8.4 or newer on this computer"
    elif "rsync: command not found" in stderr or "rsync: not found" in stderr:
        msg += " — install rsync on the remote"
    return msg


async def test_connection(settings: Settings) -> dict[str, Any]:
    """Check the destination is reachable and writable (creating the folder) and has rsync."""
    _require("rsync")
    path = _remote_path(settings)
    if not settings.sync_host.strip():
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "message": str(e)}
        ok = os.access(path, os.W_OK)
        return {"ok": ok, "message": f"{path} is ready" if ok else f"{path} is not writable"}
    _require("ssh")
    q = shlex.quote(path)
    remote = f"mkdir -p -- {q} && test -w {q} && command -v rsync >/dev/null || {{ echo 'rsync: not found' >&2; exit 1; }}"
    proc = await asyncio.create_subprocess_exec(
        *ssh_command(settings), _target(settings), remote,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
        # A password is asked through SSH_ASKPASS only: detach from any terminal so ssh never prompts in it.
        env={**os.environ, **ssh_env(settings)}, start_new_session=bool(settings.sync_password))
    try:
        _, err = await asyncio.wait_for(proc.communicate(), 30)
    except TimeoutError:
        proc.kill()
        return {"ok": False, "message": "Timed out connecting"}
    if proc.returncode == 0:
        return {"ok": True, "message": f"Connected to {_target(settings)}; {path} is ready"}
    return {"ok": False, "message": _explain(err.decode(errors="replace"), settings)}


# --- running a sync ---------------------------------------------------------------------------

PROGRESS = re.compile(r"^\s*([\d,.]+)\s+(\d+)%\s+(\S+/s)\s+(\S+)")


@dataclass
class SyncState:
    running: bool = False
    dry_run: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    ok: bool | None = None
    error: str | None = None
    percent: int = 0
    speed: str = ""  # rsync's current speed
    # A sync first checks (an rsync dry run) what needs copying, then copies it: "checking" | "copying".
    phase: str = ""
    to_copy: int = 0  # files the check found to copy
    to_copy_bytes: int = 0
    copied_bytes: int = 0  # of the files copied so far
    copy_started_at: float | None = None
    eta_seconds: int | None = None  # from the average speed so far
    files: int = 0
    bytes: int = 0
    pending: int = 0
    outside: int = 0
    transferred: int = 0
    deleted: int = 0
    changes: list[str] = field(default_factory=list)  # "+ path" sent, "- path" deleted

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


state = SyncState()
_proc: asyncio.subprocess.Process | None = None
_task: asyncio.Task | None = None
_last_publish = 0.0


def _publish(force: bool = False) -> None:
    global _last_publish
    now = time.monotonic()
    if force or now - _last_publish > 0.4:
        _last_publish = now
        hub.publish({"type": "sync", **{k: v for k, v in state.to_dict().items() if k != "changes"}})


def parse_line(line: str, sizes: dict[str, int] | None = None) -> None:
    """Fold one line of rsync output (itemized change or progress2 tick) into ``state``; ``sizes`` (path ->
    bytes) counts the bytes of the files copied. rsync's own time column is left out: it shows the time
    left while a file copies but the time taken once it's done."""
    if not line.strip():
        return
    if m := PROGRESS.match(line):
        state.percent, state.speed = int(m.group(2)), m.group(3)
        _estimate()
        return
    if line.startswith("*deleting"):
        if line.rstrip().endswith("/"):
            return  # a folder emptied by the file deletions
        state.deleted += 1
        if len(state.changes) < MAX_LISTED:
            state.changes.append("- " + line.split(None, 1)[1].strip())
    elif len(line) > 12 and line[0] in "<>" and line[1] == "f":
        state.transferred += 1
        state.copied_bytes += (sizes or {}).get(line[12:].strip(), 0)
        if len(state.changes) < MAX_LISTED:
            state.changes.append("+ " + line[12:].strip())
        _estimate()


def _estimate() -> None:
    """Time left at the average speed so far (bytes of the files copied / time copying)."""
    if state.copy_started_at is None or state.copied_bytes <= 0:
        return
    took = time.time() - state.copy_started_at
    if took >= 5:
        state.eta_seconds = round(took * (state.to_copy_bytes - state.copied_bytes) / state.copied_bytes)


async def _rsync(settings: Settings, stage_dir: Path, dry_run: bool, sizes: dict[str, int]) -> None:
    """Run rsync, folding its output into ``state``; raises SyncError when it fails."""
    global _proc
    cmd = rsync_command(settings, stage_dir, dry_run)
    log.info("sync: %s", shlex.join(cmd))
    _proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
        env={**os.environ, "LC_ALL": "C", **ssh_env(settings)}, start_new_session=bool(settings.sync_password))
    stderr_task = asyncio.create_task(_proc.stderr.read())  # type: ignore[union-attr]
    buf = ""
    while chunk := await _proc.stdout.read(4096):  # type: ignore[union-attr]
        buf += chunk.decode(errors="replace")
        *lines, buf = re.split(r"[\r\n]", buf)
        for line in lines:
            parse_line(line, sizes)
        _publish()
    parse_line(buf, sizes)
    code = await _proc.wait()
    err = (await stderr_task).decode(errors="replace")
    if code in (-15, 20):  # terminated / SIGTERM received by rsync
        raise SyncError("Cancelled")
    if code != 0:
        raise SyncError(_explain(err, settings))


async def _run(settings: Settings, dry_run: bool) -> None:
    global _proc
    try:
        plan = await asyncio.to_thread(build_plan, Path(settings.library_path))
        state.files, state.bytes, state.pending, state.outside = len(plan.files), plan.bytes, plan.pending, plan.outside
        if not plan.files and settings.sync_delete:
            raise SyncError("Nothing selected is downloaded — syncing now would empty the destination")
        stage_dir = env.data_dir / "sync" / "stage"
        await asyncio.to_thread(stage, plan, stage_dir)
        sizes = await asyncio.to_thread(lambda: {str(rel): src.stat().st_size for rel, src in plan.files})
        if not settings.sync_host.strip():
            Path(_remote_path(settings)).mkdir(parents=True, exist_ok=True)
        # A dry run first tells what needs copying, so the copy can show how far along it is.
        state.phase = "checking"
        _publish(force=True)
        await _rsync(settings, stage_dir, True, sizes)
        if not dry_run:
            state.to_copy, state.to_copy_bytes = state.transferred, state.copied_bytes
            state.transferred = state.deleted = state.copied_bytes = 0
            state.changes, state.percent = [], 0
            state.phase, state.copy_started_at = "copying", time.time()
            _publish(force=True)
            await _rsync(settings, stage_dir, False, sizes)
        state.ok, state.percent, state.eta_seconds = True, 100, 0
    except SyncError as e:
        state.ok, state.error = False, str(e)
    except Exception as e:
        log.exception("sync failed")
        state.ok, state.error = False, str(e)
    finally:
        _proc = None
        state.running = False
        state.finished_at = time.time()
        _publish(force=True)


def start(settings: Settings, dry_run: bool) -> None:
    global state, _task
    if state.running:
        raise SyncError("A sync is already running")
    _require("rsync")
    if settings.sync_host.strip():
        _require("ssh")
    _remote_path(settings)  # validates the destination
    task = asyncio.create_task(_run(settings, dry_run))  # needs the running event loop
    state = SyncState(running=True, dry_run=dry_run, started_at=time.time())
    _task = task
    _publish(force=True)


def cancel() -> bool:
    if _proc is not None and _proc.returncode is None:
        _proc.terminate()
        return True
    return False
