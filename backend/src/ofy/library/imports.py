"""Songs put by hand into an album's folder: matched to the album's missing tracks and finished like a
download (tags, cover, file name; lyrics queued)."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import col, select

from ofy.db import Album, Track, load_settings, session
from ofy.jobs import queue
from ofy.library import local
from ofy.library.scanner import AUDIO_EXTS, scan_library
from ofy.match.scoring import text_similarity, variant_penalty
from ofy.mb import logic
from ofy.mb.client import get_mb
from ofy.tagging import writers
from ofy.tagging.model import build_tag_model
from ofy.tracks import ensure_release_rows, tracks_for_release, update_track

log = logging.getLogger(__name__)

MIN_TITLE_SIM = 0.85
MAX_LENGTH_DIFF_S = 30  # a file this much longer/shorter is another recording (live, edit, ...)


@dataclass
class AddedFile:
    path: Path
    title: str
    track_id: str | None = None  # MusicBrainz track id, when the file is tagged with one
    length_ms: int | None = None


def read_added(path: Path) -> AddedFile:
    try:
        tags = writers.read_fields(path)
    except Exception:
        tags = {}
    title = (tags.get("title") or [""])[0].strip()
    if not title:  # "Artist - Title.mp3"
        title = path.stem.split(" - ", 1)[-1].strip()
    length = writers.audio_length(path)
    return AddedFile(path, title, (tags.get("musicbrainz_trackid") or [None])[0],
                     round(length * 1000) if length else None)


def match_files(files: list[AddedFile], rows: list[dict[str, Any]]) -> tuple[dict[str, AddedFile], list[AddedFile]]:
    """Pure: the release rows (``logic.tracklist``) each file is, best pairs first; and the files left over.
    A file tagged with one of the rows' MusicBrainz ids is that row; otherwise titles decide."""
    out: dict[str, AddedFile] = {}
    by_id = {r["track_id"]: r for r in rows}
    rest = []
    for f in files:
        if f.track_id in by_id and f.track_id not in out:
            out[f.track_id] = f
        else:
            rest.append(f)
    pairs = []
    for i, f in enumerate(rest):
        for r in rows:
            if r["track_id"] in out:
                continue
            sim = text_similarity(f.title, r["title"])
            if sim < MIN_TITLE_SIM or variant_penalty(r["title"], f.title) < 1:  # a live/remix/... of it isn't it
                continue
            diff = abs(f.length_ms - r["length_ms"]) / 1000 if f.length_ms and r.get("length_ms") else None
            if diff is not None and diff > MAX_LENGTH_DIFF_S:
                continue
            pairs.append((sim - (diff or 0) / 1000, i, r["track_id"]))  # same title twice: the closer length
    used: set[int] = set()
    for _score, i, tid in sorted(pairs, reverse=True):
        if i not in used and tid not in out:
            out[tid] = rest[i]
            used.add(i)
    return out, [f for i, f in enumerate(rest) if i not in used]


def album_folders(release: dict[str, Any], missing: list[str]) -> list[Path]:
    """Where the album's songs are (the folder of its downloads), or would go."""
    from ofy.pipeline import library_destination, use_library_artist

    settings = load_settings()
    with session() as s:
        album = s.get(Album, release["id"])
    folders = [Path(album.folder)] if album and album.folder else []
    for tid in missing:
        model = build_tag_model(release, tid)
        use_library_artist(model, settings)
        folder = library_destination(settings, model, "mp3", tid).parent
        if folder not in folders:
            folders.append(folder)
    return folders


def _audio_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in AUDIO_EXTS)


async def import_release(release_id: str) -> dict[str, Any]:
    """Finish the songs put into the album's folder that are tracks it misses."""
    from ofy.pipeline import finish_track

    release = await get_mb().release(release_id)
    ensure_release_rows(release)
    settings = load_settings()
    tracks = tracks_for_release(release_id)
    missing = [t.track_id for t in tracks if t.status in ("none", "failed", "needs_review")]
    folders = album_folders(release, missing)
    # songs ofy already has (as MusicBrainz tracks) aren't added ones
    candidates = [p for f in folders for p in _audio_files(f)]
    with session() as s:
        known = {t.file_path for t in s.exec(select(Track).where(col(Track.file_path).in_([str(p) for p in candidates])))
                 if not local.is_local(t.track_id)}
    added = [await asyncio.to_thread(read_added, p) for p in candidates if str(p) not in known]
    rows = [r for r in logic.tracklist(release) if r["track_id"] in set(missing)]
    matched, unmatched = match_files(added, rows)
    before = {t.track_id: t for t in tracks}
    imported, failed = [], []
    for tid, f in matched.items():
        queue.cancel_for_track(tid)
        update_track(tid, status="downloading", stage="tagging", progress=1.0, error=None)
        try:
            await finish_track(tid, release, settings, f.path, AUDIO_EXTS[f.path.suffix.lower()], fetch_lyrics=False)
        except Exception as e:
            log.warning("tagging %s failed: %s", f.path, e)
            update_track(tid, status=before[tid].status, stage=None, progress=0, error=f"{e.__class__.__name__}: {e}"[:500])
            failed.append(f.path.name)
            continue
        imported.append(before[tid].title)
        if settings.lyrics_fetch:
            queue.enqueue("lyrics", track_id=tid, release_id=release_id)
    _forget_local([str(f.path) for f in matched.values()])
    return {"imported": imported, "failed": failed, "unmatched": [f.path.name for f in unmatched],
            "folders": [str(f) for f in folders]}


async def import_library() -> dict[str, Any]:
    """Every album whose folder has songs without MusicBrainz ids: finish those that are tracks it misses."""
    await asyncio.to_thread(scan_library)  # finds the files put in since the last scan
    dirs = {str(Path(p).parent) for p in _local_paths()}
    with session() as s:
        albums = [a for a in s.exec(select(Album).where(col(Album.folder).in_(dirs))).all()
                  if not local.is_local(a.release_id)]
    imported, failed = [], []
    for a in albums:
        r = await import_release(a.release_id)
        imported += [f"{a.artist} - {t}" for t in r["imported"]]
        failed += r["failed"]
    # what's still a song without MusicBrainz ids in those folders
    unmatched = sorted(p for p in _local_paths() if str(Path(p).parent) in dirs)
    return {"albums": len(albums), "imported": imported, "failed": failed, "unmatched": unmatched}


def _local_paths() -> set[str]:
    with session() as s:
        return {p for p in s.exec(select(Track.file_path).where(col(Track.track_id).startswith(local.PREFIX))).all() if p}


def _forget_local(paths: list[str]) -> None:
    """The rows of files that were songs without MusicBrainz ids (from a scan), and albums left empty."""
    if not paths:
        return
    with session() as s:
        rows = s.exec(select(Track).where(col(Track.track_id).startswith(local.PREFIX),
                                          col(Track.file_path).in_(paths))).all()
        albums = {t.release_id for t in rows}
        for t in rows:
            s.delete(t)
        s.flush()
        for rid in albums:
            if s.exec(select(Track).where(Track.release_id == rid)).first() is None:
                a = s.get(Album, rid)
                if a:
                    s.delete(a)
        s.commit()
