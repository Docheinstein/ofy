"""Download / matching / lyrics / retag actions and the downloads view."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import col, delete, select

from ofy.db import Album, Job, Track, load_settings, session
from ofy.jobs import queue
from ofy.library import local
from ofy.match.engine import match_release
from ofy.mb import logic
from ofy.mb.client import MusicBrainzError, NotFound, get_mb
from ofy.pipeline import enqueue_album, enqueue_track
from ofy.tagging import writers
from ofy.tracks import ensure_release_rows, get_track, save_candidates, tracks_for_release, update_track
from ofy.ytimport import JOB_KIND as YT_RESOLVE

router = APIRouter(prefix="/api", tags=["actions"])


async def _guard(coro):
    try:
        return await coro
    except NotFound as e:
        raise HTTPException(404, "Not found on MusicBrainz") from e
    except MusicBrainzError as e:
        raise HTTPException(502, str(e)) from e


def _not_local(mbid: str | None) -> None:
    """Downloading, matching and MusicBrainz retagging don't apply to local files."""
    if local.is_local(mbid):
        raise HTTPException(400, "A local file: not from MusicBrainz or YouTube")


@router.post("/release/{release_id}/download")
async def download_release(release_id: str) -> dict[str, Any]:
    _not_local(release_id)
    n = await _guard(enqueue_album(release_id))
    return {"queued": n}


@router.post("/release/{release_id}/tracks/{track_id}/download")
async def download_track(release_id: str, track_id: str) -> dict[str, Any]:
    _not_local(release_id)
    try:
        await _guard(enqueue_track(release_id, track_id))
    except KeyError as e:
        raise HTTPException(404, "Track not on release") from e
    return {"queued": 1}


@router.post("/recording/{recording_id}/download")
async def download_recording(recording_id: str, release: str | None = None) -> dict[str, Any]:
    """Download a song found via search: pick a release containing it, then queue that track."""
    mb = get_mb()
    rec = await _guard(mb.recording(recording_id))
    release_id = release
    if release_id is None:
        best = logic.pick_canonical_release(rec.get("releases") or [])
        if best is None:
            raise HTTPException(404, "Recording is not on any release")
        release_id = best["id"]
    full = await _guard(mb.release(release_id))
    track_id = next((r["track_id"] for r in logic.tracklist(full) if r["recording_id"] == recording_id), None)
    if track_id is None:
        raise HTTPException(404, "Recording not found on release")
    await enqueue_track(release_id, track_id)
    return {"queued": 1, "release_id": release_id, "track_id": track_id,
            "release_group_id": (full.get("release-group") or {}).get("id")}


@router.post("/release/{release_id}/tracks/{track_id}/candidates")
async def find_candidates(release_id: str, track_id: str) -> dict[str, Any]:
    _not_local(release_id)
    release = await _guard(get_mb().release(release_id))
    ensure_release_rows(release)
    settings = load_settings()
    result = await match_release(release, settings.match_threshold, only_track_ids={track_id})
    m = result.tracks.get(track_id)
    if m is None:
        raise HTTPException(404, "Track not on release")
    cands = [c.to_dict() for c in m.candidates]
    save_candidates(track_id, cands)
    t = get_track(track_id)
    if t and t.match_source != "manual" and t.status in ("none", "needs_review") and m.best:
        update_track(track_id, video_id=m.best.candidate.video_id, match_score=m.score, match_source=m.source)
    return {"candidates": cands}


@router.post("/track/{track_id}/retry")
def retry(track_id: str) -> dict[str, Any]:
    _not_local(track_id)
    t = get_track(track_id)
    if t is None:
        raise HTTPException(404, "Unknown track")
    if t.status in ("queued", "downloading"):
        return {"queued": 0}
    # A failed *match* gets matched again; a failed download keeps its (possibly manual) match.
    update_track(track_id, status="queued", stage=None, progress=0, error=None)
    queue.enqueue("download", track_id=track_id, release_id=t.release_id)
    return {"queued": 1}


class ManualMatch(BaseModel):
    video_id: str


@router.post("/track/{track_id}/match")
def choose_match(track_id: str, body: ManualMatch) -> dict[str, Any]:
    _not_local(track_id)
    t = get_track(track_id)
    if t is None:
        raise HTTPException(404, "Unknown track")
    cands = json.loads(t.candidates or "[]")
    score = next((c.get("score") for c in cands if c.get("video_id") == body.video_id), None)
    queue.cancel_for_track(track_id)
    update_track(track_id, video_id=body.video_id, match_source="manual",
                 match_score=score if score is not None else 1.0, status="queued", stage=None, progress=0,
                 error=None)
    queue.enqueue("download", track_id=track_id, release_id=t.release_id)
    return {"queued": 1}


@router.get("/track/{track_id}")
def track_detail(track_id: str) -> dict[str, Any]:
    t = get_track(track_id)
    if t is None:
        raise HTTPException(404, "Unknown track")
    tags = None
    fields = None
    lyrics_text = None
    if t.file_path and Path(t.file_path).is_file():
        try:
            tags = writers.read_display(Path(t.file_path))
            fields = _editable_fields(Path(t.file_path))
        except Exception as e:
            tags = {"error": [str(e)]}
    if t.lyrics_path and Path(t.lyrics_path).is_file():
        lyrics_text = Path(t.lyrics_path).read_text(encoding="utf-8", errors="replace")
    return {
        **t.model_dump(exclude={"candidates"}),
        "candidates": json.loads(t.candidates or "[]"),
        "tags": tags,
        "fields": fields,
        "editable": writers.EDITABLE,
        "lyrics_text": lyrics_text,
        "threshold": load_settings().match_threshold,
    }


def _editable_fields(path: Path) -> dict[str, list[str]]:
    """The file's tags by internal name, in editor order (pseudo-fields and lyrics left out)."""
    fields = writers.read_fields(path)
    return {name: fields[name] for name in writers.EDITABLE if name in fields}


class TagEdit(BaseModel):
    # internal tag name -> new values; an empty list removes the tag
    changes: dict[str, list[str]]


@router.put("/track/{track_id}/tags")
async def edit_tags(track_id: str, body: TagEdit) -> dict[str, Any]:
    t = get_track(track_id)
    if t is None:
        raise HTTPException(404, "Unknown track")
    if t.status != "done" or not t.file_path or not Path(t.file_path).is_file():
        raise HTTPException(409, "Track is not downloaded")
    path = Path(t.file_path)
    try:
        await asyncio.to_thread(writers.edit_fields, path, body.changes)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    if local.is_local(track_id):
        # a local track is what its tags say: show the edit everywhere (title, album, ...)
        from ofy.library.scanner import scan_library

        await asyncio.to_thread(scan_library)
    return {"fields": _editable_fields(path)}


@router.post("/track/{track_id}/lyrics")
def refetch_lyrics(track_id: str) -> dict[str, Any]:
    t = get_track(track_id)
    if t is None or t.status != "done":
        raise HTTPException(400, "Track is not downloaded")
    queue.enqueue("lyrics", track_id=track_id, release_id=t.release_id)
    return {"queued": 1}


def _queue_missing_lyrics(tracks: list[Track]) -> int:
    n = 0
    for t in tracks:
        if t.status == "done" and t.lyrics_status in ("none", "not_found"):
            queue.enqueue("lyrics", track_id=t.track_id, release_id=t.release_id)
            n += 1
    return n


@router.post("/release/{release_id}/lyrics")
def album_missing_lyrics(release_id: str) -> dict[str, Any]:
    return {"queued": _queue_missing_lyrics(tracks_for_release(release_id))}


@router.post("/library/lyrics")
def library_missing_lyrics() -> dict[str, Any]:
    with session() as s:
        tracks = list(s.exec(select(Track).where(Track.status == "done")).all())
    return {"queued": _queue_missing_lyrics(tracks)}


@router.post("/release/{release_id}/retag")
def retag(release_id: str) -> dict[str, Any]:
    _not_local(release_id)
    if not any(t.status == "done" for t in tracks_for_release(release_id)):
        raise HTTPException(400, "Nothing downloaded for this release")
    queue.enqueue("retag", release_id=release_id)
    return {"queued": 1}


@router.get("/lyrics/{recording_id}")
def lyrics_for_recording(recording_id: str) -> dict[str, Any]:
    with session() as s:
        tracks = s.exec(select(Track).where(Track.recording_id == recording_id, Track.status == "done")).all()
    for t in tracks:
        if not t.file_path:
            continue
        audio = Path(t.file_path)
        lrc = audio.with_suffix(".lrc")
        if lrc.is_file():
            return {"status": "synced", "synced": lrc.read_text(encoding="utf-8", errors="replace"), "plain": None}
        try:
            plain = writers.get_lyrics(audio) if audio.is_file() else None
        except Exception:
            plain = None
        if plain:
            return {"status": "plain", "synced": None, "plain": plain}
        return {"status": t.lyrics_status, "synced": None, "plain": None}
    return {"status": "none", "synced": None, "plain": None}


# --- downloads view ---------------------------------------------------------------------------

def _item(job: Job, t: Track | None, albums: dict[str, Album]) -> dict[str, Any]:
    album = albums.get(job.release_id or (t.release_id if t else ""))
    return {
        "job_id": job.id,
        "kind": job.kind,
        "track_id": job.track_id,
        "release_id": job.release_id or (t.release_id if t else None),
        "release_group_id": album.release_group_id if album else (t.release_group_id if t else None),
        "title": t.title if t else (album.title if album else job.kind),
        "artist": t.artist if t else (album.artist if album else ""),
        "album": album.title if album else None,
        "status": job.status,
        "track_status": t.status if t else None,
        "stage": t.stage if t else None,
        "progress": t.progress if t else 0,
        "error": job.error or (t.error if t else None),
        "attempts": job.attempts,
        "updated_at": job.updated_at,
    }


@router.get("/library/albums")
def get_library_albums() -> list[dict[str, Any]]:
    return library_albums()


@router.get("/downloads")
def downloads(limit: int = 100) -> dict[str, Any]:
    with session() as s:
        # YouTube links being looked up on MusicBrainz are listed with their imports instead
        shown = Job.kind != YT_RESOLVE
        active = list(s.exec(select(Job).where(col(Job.status).in_(["pending", "running"]), shown)
                             .order_by(col(Job.created_at))).all())
        recent = list(s.exec(select(Job).where(col(Job.status).in_(["done", "failed"]), shown)
                             .order_by(col(Job.updated_at).desc()).limit(limit)).all())
        ids = {j.track_id for j in active + recent if j.track_id}
        tracks = {t.track_id: t for t in s.exec(select(Track).where(col(Track.track_id).in_(ids))).all()}
        albums = {a.release_id: a for a in s.exec(select(Album)).all()}
    # Show running first, then pending
    active.sort(key=lambda j: (j.status != "running", j.created_at))
    return {
        "active": [_item(j, tracks.get(j.track_id or ""), albums) for j in active],
        "recent": [_item(j, tracks.get(j.track_id or ""), albums) for j in recent],
    }


@router.post("/downloads/clear")
def clear_finished() -> dict[str, Any]:
    with session() as s:
        s.exec(delete(Job).where(col(Job.status).in_(["done", "failed"])))  # type: ignore[call-overload]
        s.commit()
    return {"ok": True}


@router.post("/downloads/retry-failed")
def retry_failed() -> dict[str, Any]:
    with session() as s:
        tracks = list(s.exec(select(Track).where(Track.status == "failed")).all())
    for t in tracks:
        update_track(t.track_id, status="queued", stage=None, progress=0, error=None)
        queue.enqueue("download", track_id=t.track_id, release_id=t.release_id)
    return {"queued": len(tracks)}


def library_albums() -> list[dict[str, Any]]:
    from ofy.library.status import album_summary

    with session() as s:
        albums = list(s.exec(select(Album)).all())
        tracks = list(s.exec(select(Track)).all())
    by_rel: dict[str, list[Track]] = {}
    for t in tracks:
        by_rel.setdefault(t.release_id, []).append(t)
    out = []
    for a in albums:
        ts = by_rel.get(a.release_id, [])
        summ = album_summary([t.status for t in ts], a.track_count)
        if summ["done"] == 0 and summ["active"] == 0 and summ["failed"] == 0 and summ["needs_review"] == 0:
            continue
        lyr: dict[str, int] = {}
        for t in ts:
            if t.status == "done":
                lyr[t.lyrics_status] = lyr.get(t.lyrics_status, 0) + 1
        # the downloaded songs, for the library tree (whether each is synced is resolved by the UI)
        done = sorted((t for t in ts if t.status == "done"), key=lambda t: (t.disc, t.position))
        songs = [{"track_id": t.track_id, "recording_id": t.recording_id, "disc": t.disc, "position": t.position,
                  "title": t.title, "artist": t.artist, "length_ms": t.length_ms, "lyrics_status": t.lyrics_status}
                 for t in done]
        out.append({**a.model_dump(), "library": summ, "lyrics": lyr, "tracks": songs})
    out.sort(key=lambda x: (x["artist"].lower(), x["year"] or "", x["title"].lower()))
    return out


@router.get("/library/status")
async def library_status() -> dict[str, Any]:
    """Whether the library folder is there; when it's not (a drive not attached) the songs can't play."""
    from ofy.library.scanner import library_missing

    path = Path(load_settings().library_path).expanduser()
    return {"available": not await asyncio.to_thread(library_missing, path), "path": str(path)}


@router.post("/library/rescan")
async def rescan() -> dict[str, Any]:
    from ofy.library.scanner import scan_library

    result = await asyncio.to_thread(scan_library)
    return {"changed": len(result.changes) + result.local_changes, "scanned": result.scanned, "missing": result.missing}
