"""Library scanner: reconcile the database with what's actually on disk.

Detects audio files deleted/moved/added outside the app (matched by their MusicBrainz release
track id tag) and .lrc lyrics sidecars added or removed.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlmodel import select

from ofy.db import Album, Track, load_settings, session
from ofy.events import hub
from ofy.tagging import writers

log = logging.getLogger(__name__)

AUDIO_EXTS = {".mp3": "mp3", ".m4a": "m4a", ".opus": "opus"}


@dataclass
class DbTrack:
    track_id: str
    status: str
    file_path: str | None
    lyrics_status: str
    file_format: str | None = None
    lyrics_path: str | None = None


@dataclass
class FoundFile:
    path: str
    fmt: str
    lyrics: str  # synced (.lrc on disk) | plain (embedded, only read for unknown files) | none
    tags: dict[str, list[str]] | None = None  # only read for files the DB doesn't know


@dataclass
class Change:
    track_id: str
    fields: dict
    new_row: dict | None = None  # tag data to create a Track/Album row for unknown files


@dataclass
class ScanResult:
    changes: list[Change] = field(default_factory=list)
    scanned: int = 0


def lyrics_from_sidecars(previous: str, on_disk: str) -> str:
    """A .lrc wins; without one keep plain (embedded in the tags)/instrumental/not_found, else none."""
    if on_disk == "synced":
        return on_disk
    if previous in ("plain", "instrumental", "not_found"):
        return previous
    return "none"


def plan_reconcile(db: list[DbTrack], found: dict[str, FoundFile]) -> list[Change]:
    """Pure reconciliation. ``found`` maps release-track id -> file found on disk."""
    changes: list[Change] = []
    known = {t.track_id: t for t in db}
    for t in db:
        f = found.get(t.track_id)
        if t.status == "done":
            if f is None:
                changes.append(Change(t.track_id, {
                    "status": "none", "file_path": None, "file_format": None, "progress": 0,
                    "lyrics_status": "none", "lyrics_path": None, "stage": None,
                }))
                continue
            desired = {
                "file_path": f.path,
                "file_format": f.fmt,
                "lyrics_status": lyrics_from_sidecars(t.lyrics_status, f.lyrics),
                "lyrics_path": _sidecar_path(f.path, f.lyrics),
            }
            current = {"file_path": t.file_path, "file_format": t.file_format,
                       "lyrics_status": t.lyrics_status, "lyrics_path": t.lyrics_path}
            diff = {k: v for k, v in desired.items() if current[k] != v}
            if diff:
                changes.append(Change(t.track_id, diff))
        elif f is not None and t.status in ("none", "failed", "needs_review"):
            # File (re)appeared on disk, e.g. restored from backup or copied in.
            changes.append(Change(t.track_id, {
                "status": "done", "file_path": f.path, "file_format": f.fmt, "progress": 1.0, "error": None,
                "lyrics_status": lyrics_from_sidecars(t.lyrics_status, f.lyrics),
                "lyrics_path": _sidecar_path(f.path, f.lyrics),
            }))
    for tid, f in found.items():
        if tid not in known and f.tags:
            changes.append(Change(tid, {
                "status": "done", "file_path": f.path, "file_format": f.fmt, "progress": 1.0,
                "lyrics_status": f.lyrics, "lyrics_path": _sidecar_path(f.path, f.lyrics),
            }, new_row=f.tags))
    return changes


def _sidecar_path(audio: str, lyrics: str) -> str | None:
    if not audio:
        return None
    if lyrics == "synced":
        return str(Path(audio).with_suffix(".lrc"))
    return None


def _walk(root: Path) -> list[Path]:
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.startswith("."):
                continue
            if Path(name).suffix.lower() in AUDIO_EXTS:
                out.append(Path(dirpath) / name)
    return out


def _sidecar_state(p: Path) -> str:
    return "synced" if p.with_suffix(".lrc").is_file() else "none"


def scan_library() -> ScanResult:
    """Blocking: walk the library, reconcile, apply changes. Run in a thread."""
    settings = load_settings()
    root = Path(settings.library_path).expanduser()
    with session() as s:
        rows = list(s.exec(select(Track)).all())
    db = [DbTrack(t.track_id, t.status, t.file_path, t.lyrics_status, t.file_format, t.lyrics_path) for t in rows]
    by_path = {t.file_path: t.track_id for t in rows if t.file_path}
    found: dict[str, FoundFile] = {}
    files = _walk(root) if root.is_dir() else []
    for p in files:
        sp = str(p)
        fmt = AUDIO_EXTS[p.suffix.lower()]
        lyr = _sidecar_state(p)
        tid = by_path.get(sp)
        if tid:
            found.setdefault(tid, FoundFile(sp, fmt, lyr))
            continue
        try:
            tags = writers.read_fields(p)
        except Exception as e:
            log.info("unreadable file %s: %s", p, e)
            continue
        tid = (tags.get("musicbrainz_trackid") or [None])[0]
        if not tid or tid in found:
            continue
        if lyr == "none" and tags.get("lyrics"):
            lyr = "plain"
        found[tid] = FoundFile(sp, fmt, lyr, tags)
    # A tracked file that's been moved still shows up under its id via tags; a known path
    # that still exists keeps priority over any duplicate copy.
    changes = plan_reconcile(db, found)
    _apply(changes)
    if changes:
        hub.publish({"type": "library", "changed": len(changes)})
    log.info("library scan: %d files, %d changes", len(files), len(changes))
    return ScanResult(changes, len(files))


def _first(tags: dict[str, list[str]], k: str, default: str = "") -> str:
    v = tags.get(k)
    return v[0] if v else default


def _int(tags: dict[str, list[str]], k: str, default: int = 1) -> int:
    try:
        return int(_first(tags, k, str(default)))
    except ValueError:
        return default


def _apply(changes: list[Change]) -> None:
    if not changes:
        return
    with session() as s:
        for c in changes:
            t = s.get(Track, c.track_id)
            if t is None and c.new_row is not None:
                tags = c.new_row
                release_id = _first(tags, "musicbrainz_albumid")
                rg_id = _first(tags, "musicbrainz_releasegroupid")
                if not release_id:
                    continue
                t = Track(
                    track_id=c.track_id,
                    recording_id=_first(tags, "musicbrainz_recordingid"),
                    release_id=release_id,
                    release_group_id=rg_id,
                    disc=_int(tags, "discnumber"),
                    position=_int(tags, "tracknumber"),
                    title=_first(tags, "title"),
                    artist=_first(tags, "artist"),
                    video_id=_first(tags, "youtube_video_id") or None,
                )
                length = _first(tags, "length")
                t.length_ms = int(length) if length.isdigit() else None
                if s.get(Album, release_id) is None:
                    s.add(Album(
                        release_id=release_id, release_group_id=rg_id, title=_first(tags, "album"),
                        artist=_first(tags, "albumartist"),
                        artist_id=_first(tags, "musicbrainz_albumartistid") or None,
                        year=_first(tags, "originalyear") or _first(tags, "date")[:4] or None,
                        # Best effort until the release page is visited (multi-disc totals unknown here)
                        track_count=_int(tags, "totaltracks", 0) * max(1, _int(tags, "totaldiscs")),
                        folder=str(Path(c.fields["file_path"]).parent),
                    ))
            if t is None:
                continue
            for k, v in c.fields.items():
                setattr(t, k, v)
            t.updated_at = time.time()
            s.add(t)
        s.commit()
