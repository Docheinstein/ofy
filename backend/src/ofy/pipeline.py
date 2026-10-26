"""Job handlers: album matching, track download (match → download → convert → tag → lyrics → move),
re-tagging and lyrics refresh."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import shutil
import time
from pathlib import Path

from ofy import artistimage, coverart
from ofy.config import Settings, env
from ofy.db import Album, Job, Track, load_settings, session
from ofy.download import convert as conv
from ofy.download.paths import artist_key, library_artist_name, plain_marks, render_template
from ofy.download.ytdlp import download_audio
from ofy.jobs import PermanentError, queue
from ofy.library import local
from ofy.lyrics import service as lyrics_service
from ofy.match.engine import TrackMatch, match_release
from ofy.match.scoring import COMPOSITE_SEP
from ofy.mb.client import get_mb
from ofy.tagging import writers
from ofy.tagging.mapping import lyrics_missing_from
from ofy.tagging.model import TagModel, build_tag_model
from ofy.tracks import (
    ensure_release_rows,
    get_track,
    publish_progress,
    save_candidates,
    tracks_for_release,
    update_track,
)

log = logging.getLogger(__name__)

SIDECAR_EXTS = (".lrc", ".txt")  # moved/removed along with the audio; .txt only from older versions


# --- enqueueing --------------------------------------------------------------------------------

async def enqueue_album(release_id: str) -> int:
    release = await get_mb().release(release_id)
    tracks = ensure_release_rows(release)
    n = 0
    for t in tracks:
        if t.status in ("none", "failed"):
            update_track(t.track_id, status="queued", stage=None, progress=0, error=None)
            n += 1
    queue.enqueue("match_album", release_id=release_id)
    return n


async def enqueue_track(release_id: str, track_id: str) -> None:
    release = await get_mb().release(release_id)
    ensure_release_rows(release)
    t = get_track(track_id)
    if t is None:
        raise KeyError(track_id)
    if t.status in ("queued", "downloading"):
        return
    update_track(track_id, status="queued", stage=None, progress=0, error=None)
    queue.enqueue("download", track_id=track_id, release_id=release_id)


def apply_match(track_id: str, m: TrackMatch, threshold: float) -> bool:
    """Persist a match; returns True if confident enough to download."""
    save_candidates(track_id, [c.to_dict() for c in m.candidates])
    if m.best is None or m.score < threshold:
        update_track(
            track_id, status="needs_review", stage=None, progress=0,
            video_id=m.best.candidate.video_id if m.best else None,
            match_score=m.score if m.best else None, match_source=m.source,
            error=None if m.best else "No match found on YouTube Music",
        )
        return False
    update_track(track_id, video_id=m.best.candidate.video_id, match_score=m.score, match_source=m.source,
                 status="queued", stage=None)
    return True


# --- handlers ------------------------------------------------------------------------------------

async def handle_match_album(job: Job) -> None:
    settings = load_settings()
    release = await get_mb().release(job.release_id)  # type: ignore[arg-type]
    ensure_release_rows(release)
    tracks = [t for t in tracks_for_release(job.release_id) if t.status == "queued"]  # type: ignore[arg-type]
    # Keep manual choices; re-match everything else that is queued.
    to_match = {t.track_id for t in tracks if t.match_source != "manual"}
    for tid in to_match:
        update_track(tid, status="downloading", stage="matching", progress=0)
    try:
        result = await match_release(release, settings.match_threshold, only_track_ids=to_match) if to_match else None
    except Exception:
        for tid in to_match:
            update_track(tid, status="queued", stage=None)
        raise
    for t in tracks:
        ok = True
        if result and t.track_id in result.tracks:
            ok = apply_match(t.track_id, result.tracks[t.track_id], settings.match_threshold)
        if ok:
            queue.enqueue("download", track_id=t.track_id, release_id=t.release_id)


async def handle_download(job: Job) -> None:
    t = get_track(job.track_id)  # type: ignore[arg-type]
    if t is None:
        raise PermanentError("track not found")
    if t.status not in ("queued", "downloading", "failed"):
        log.info("skip download of %s (status %s)", t.track_id, t.status)
        return
    settings = load_settings()
    release = await get_mb().release(t.release_id)
    work = env.tmp_dir / f"job-{job.id}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        await _download_track(t.track_id, release, settings, work)
    except Exception as e:
        update_track(t.track_id, stage=None, progress=0, error=f"{e.__class__.__name__}: {e}"[:500])
        raise
    finally:
        shutil.rmtree(work, ignore_errors=True)


async def _download_track(track_id: str, release: dict, settings: Settings, work: Path) -> None:
    t = update_track(track_id, status="downloading", stage="matching", progress=0, error=None)
    if not t.video_id:
        result = await match_release(release, settings.match_threshold, only_track_ids={track_id})
        if not apply_match(track_id, result.tracks[track_id], settings.match_threshold):
            return  # needs review
        t = update_track(track_id, status="downloading", stage="matching")
    video_ids = t.video_id.split(COMPOSITE_SEP)  # type: ignore[union-attr]
    fmt = settings.output_format

    # 1. download
    t = update_track(track_id, stage="downloading", progress=0)
    loop = asyncio.get_running_loop()
    last_pub = [0.0]
    sources = []
    for i, vid in enumerate(video_ids):
        await asyncio.sleep(random.uniform(0.3, 1.5))  # jitter: never hammer YouTube

        def on_progress(p: float, i=i) -> None:
            now = time.monotonic()
            if now - last_pub[0] >= 0.3 or p >= 1.0:
                last_pub[0] = now
                overall = (i + p) / len(video_ids)
                loop.call_soon_threadsafe(publish_progress, t, overall, "downloading")

        audio = await asyncio.to_thread(
            download_audio, vid, work / f"src{i}", fmt, cookies_path=settings.cookies_path or None,
            progress=on_progress,
        )
        sources.append(audio)
    # 2. convert
    t = update_track(track_id, stage="converting", progress=1.0)
    src_codec = conv.normalize_codec(sources[0].acodec) or conv.probe_codec(sources[0].path)
    ext = conv.EXT[fmt]
    tmp_out = work / f"out.{ext}"
    copied = await asyncio.to_thread(conv.convert, [s.path for s in sources], tmp_out, fmt,
                                     src_codec=src_codec, mp3_quality=settings.mp3_quality)
    log.info("%s: %s %s -> %s", t.title, "remuxed" if copied else "encoded", src_codec, fmt)
    await finish_track(track_id, release, settings, tmp_out, fmt)


async def finish_track(track_id: str, release: dict, settings: Settings, audio: Path, fmt: str, *,
                       fetch_lyrics: bool = True) -> Path:
    """Tag ``audio`` (cover included), fetch its lyrics and move it into the library: the track is done.
    Returns where the file ended up."""
    # 3. tag
    t = update_track(track_id, stage="tagging")
    model = build_tag_model(release, track_id, youtube_video_id=t.video_id,
                            genre_mode=settings.genre_mode, genre_separator=settings.genre_separator)
    use_library_artist(model, settings)
    rg_id = (release.get("release-group") or {}).get("id")
    cover = await coverart.front_for_release(release["id"], rg_id, "1200")
    await asyncio.to_thread(writers.write_tags, audio, model, cover)
    # 4. lyrics (best effort, never fails the download)
    lyr: lyrics_service.LyricsOutcome | None = None
    if settings.lyrics_fetch and fetch_lyrics:
        t = update_track(track_id, stage="lyrics")
        audio_s = await asyncio.to_thread(writers.audio_length, audio)
        lyr = await lyrics_service.fetch_for_model(model, settings, audio_s=audio_s)
        if lyr.embed_text and settings.lyrics_embed:
            try:
                await asyncio.to_thread(writers.set_lyrics, audio, lyr.embed_text)
            except Exception as e:  # pragma: no cover - defensive
                log.warning("embedding lyrics failed: %s", e)
        if lyr.missing:
            await asyncio.to_thread(writers.set_lyrics_missing, audio, lyr.missing)
    # 5. move atomically into the library
    dest = library_destination(settings, model, conv.EXT[fmt], track_id)
    old = Path(t.file_path) if t.file_path else None
    await asyncio.to_thread(atomic_move, audio, dest)
    if old and old != dest:
        remove_with_sidecars(old)
    lyrics_status, lyrics_path = t.lyrics_status, t.lyrics_path
    if lyr is not None:
        lyrics_status, lp = lyrics_service.write_sidecar(dest, lyr, model, settings)
        lyrics_path = str(lp) if lp else None
    _record_album_folder(t.release_id, dest.parent)
    await _cache_artist_image(model)
    update_track(
        track_id, status="done", stage=None, progress=1.0, error=None, file_path=str(dest), file_format=fmt,
        lyrics_status=lyrics_status, lyrics_path=lyrics_path,
    )
    return dest


def use_library_artist(model: TagModel, settings: Settings) -> None:
    """Credit the album artist as the library's folder for them is named, so an album credited to
    "Black Eyed Peas" joins "The Black Eyed Peas" (and a retag doesn't split a merged folder again)."""
    if not settings.path_template.startswith("{albumartist}/"):
        return
    try:
        folders = [p.name for p in Path(settings.library_path).expanduser().iterdir() if p.is_dir()]
    except OSError:
        folders = []
    old, name = model.albumartist, library_artist_name(model.albumartist, folders)
    key = artist_key(old)
    model.albumartist = name
    model.albumartistsort, model.artistsort = plain_marks(model.albumartistsort), plain_marks(model.artistsort)
    model.albumartists = [name if artist_key(a) == key else a for a in model.albumartists]
    model.artists = [name if artist_key(a) == key else a for a in model.artists]
    # The track's own credit, spelled its own way, may start with the album artist: "<name> feat. ...".
    head, rest = model.artist[:len(old)], model.artist[len(old):]
    if artist_key(head) == key and rest[:1] in ("", " ", ","):
        model.artist = name + rest

def library_destination(settings: Settings, model: TagModel, ext: str, track_id: str) -> Path:
    root = Path(settings.library_path).expanduser()
    rel = render_template(settings.path_template, model.path_values(ext))
    dest = root / rel
    # Two tracks can render to the same name (e.g. the same song twice on a release, now that the
    # default name has no track number): never clobber another track, disambiguate with disc-track.
    if dest.exists():
        try:
            ids = writers.read_mbids(dest)
        except Exception:
            ids = None
        if ids and ids.get("track_id") and ids["track_id"] != track_id:
            dest = dest.with_name(f"{dest.stem} ({model.discnumber}-{model.tracknumber:02d}){dest.suffix}")
    return dest


def atomic_move(src: Path, dest: Path) -> None:
    """Copy into the destination directory under a temp name, fsync, then rename (atomic)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.part")
    try:
        os.replace(src, tmp)  # same filesystem: cheap
    except OSError:
        shutil.copyfile(src, tmp)
        src.unlink(missing_ok=True)
    with open(tmp, "rb") as f:
        os.fsync(f.fileno())
    os.replace(tmp, dest)


def remove_with_sidecars(path: Path) -> None:
    for p in [path] + [path.with_suffix(e) for e in SIDECAR_EXTS]:
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


async def _cache_artist_image(model: TagModel) -> None:
    ids = model.musicbrainz_albumartistids
    try:
        await artistimage.prefetch_artist_image(ids[0] if ids else None)
    except Exception as e:  # never fails a download
        log.warning("caching artist image failed: %s", e)


def _record_album_folder(release_id: str, folder: Path) -> None:
    with session() as s:
        a = s.get(Album, release_id)
        if a:
            a.folder = str(folder)
            s.add(a)
            s.commit()


async def on_download_failed(job: Job, final_error: str) -> None:
    if not job.track_id:
        return
    t = get_track(job.track_id)
    if t is None:
        return
    if job.status == "failed":
        update_track(job.track_id, status="failed", stage=None, progress=0,
                     error=(final_error or job.error or "failed")[:500])
    else:
        update_track(job.track_id, status="queued", stage=None, progress=0, error=job.error)


async def on_match_album_failed(job: Job, final_error: str) -> None:
    if job.status != "failed" or not job.release_id:
        return
    for t in tracks_for_release(job.release_id):
        if t.status in ("queued", "downloading"):
            update_track(t.track_id, status="failed", stage=None, error=f"Matching failed: {final_error}"[:500])


# --- retag / lyrics ---------------------------------------------------------------------------------

async def handle_retag(job: Job) -> None:
    """Rewrite tags of downloaded files from *fresh* MusicBrainz data; never touches YouTube."""
    settings = load_settings()
    release = await get_mb().release(job.release_id, fresh=True)  # type: ignore[arg-type]
    ensure_release_rows(release)
    rg_id = (release.get("release-group") or {}).get("id")
    cover = await coverart.front_for_release(release["id"], rg_id, "1200")
    for t in tracks_for_release(job.release_id):  # type: ignore[arg-type]
        if t.status != "done" or not t.file_path or not Path(t.file_path).is_file():
            continue
        path = Path(t.file_path)
        model = build_tag_model(release, t.track_id, youtube_video_id=t.video_id,
                                genre_mode=settings.genre_mode, genre_separator=settings.genre_separator)
        use_library_artist(model, settings)
        fields = await asyncio.to_thread(writers.read_fields, path)
        if settings.lyrics_embed:
            model.lyrics = (fields.get("lyrics") or [None])[0]
        model.lyrics_missing = lyrics_missing_from(fields)
        update_track(t.track_id, stage="tagging")
        await asyncio.to_thread(writers.write_tags, path, model, cover)
        # Metadata changes may imply a new path: move audio + sidecars along.
        ext = path.suffix.lstrip(".")
        dest = library_destination(settings, model, ext, t.track_id)
        lyrics_path = t.lyrics_path
        if dest != path:
            await asyncio.to_thread(atomic_move, path, dest)
            for e in SIDECAR_EXTS:
                side = path.with_suffix(e)
                if side.exists():
                    os.replace(side, dest.with_suffix(e))
                    lyrics_path = str(dest.with_suffix(e))
            _cleanup_empty_dirs(path.parent, Path(settings.library_path))
        update_track(t.track_id, stage=None, file_path=str(dest), lyrics_path=lyrics_path)


def _cleanup_empty_dirs(folder: Path, root: Path) -> None:
    try:
        root = root.resolve()
        folder = folder.resolve()
        while folder != root and root in folder.parents:
            # cover.jpg: written by older versions, not worth keeping a folder for
            leftovers = [p for p in folder.iterdir() if p.name != "cover.jpg"]
            if leftovers:
                return
            for p in folder.iterdir():
                p.unlink()
            folder.rmdir()
            folder = folder.parent
    except OSError:
        return


async def handle_lyrics(job: Job) -> None:
    t = get_track(job.track_id)  # type: ignore[arg-type]
    if t is None or t.status != "done" or not t.file_path or not Path(t.file_path).is_file():
        return
    settings = load_settings()
    if local.is_local(t.track_id):
        model = _local_tag_model(t)
    else:
        release = await get_mb().release(t.release_id)
        model = build_tag_model(release, t.track_id, youtube_video_id=t.video_id)
    path = Path(t.file_path)
    update_track(t.track_id, stage="lyrics")
    try:
        audio_s = await asyncio.to_thread(writers.audio_length, path)
        lyr = await lyrics_service.fetch_for_model(model, settings, audio_s=audio_s)
        # A failed lookup keeps what's there: the tags may hold the only copy of plain lyrics.
        if lyr.status != "error":
            if settings.lyrics_embed:
                await asyncio.to_thread(writers.set_lyrics, path, lyr.embed_text)
            await asyncio.to_thread(writers.set_lyrics_missing, path, lyr.missing)
        status, lp = lyrics_service.write_sidecar(path, lyr, model, settings)
    finally:
        update_track(t.track_id, stage=None, publish=False)
    update_track(t.track_id, lyrics_status=status, lyrics_path=str(lp) if lp else None)


def _local_tag_model(t: Track) -> TagModel:
    """What the lyrics lookup needs of a local track, from its (tag-derived) rows."""
    with session() as s:
        album = s.get(Album, t.release_id)
    album_artist = album.artist if album else t.artist
    return TagModel(
        title=t.title, artist=t.artist, artists=[t.artist], artistsort=t.artist,
        album=album.title if album else "", albumartist=album_artist, albumartists=[album_artist],
        albumartistsort=album_artist, tracknumber=t.position, totaltracks=album.track_count if album else 0,
        discnumber=t.disc, totaldiscs=1, length_ms=t.length_ms,
    )


def register_handlers() -> None:
    queue.register("match_album", handle_match_album, on_match_album_failed)
    queue.register("download", handle_download, on_download_failed)
    queue.register("retag", handle_retag)
    queue.register("lyrics", handle_lyrics)

    from ofy import ytimport

    queue.register(ytimport.JOB_KIND, ytimport.handle_resolve, ytimport.on_resolve_failed)


def candidates_of(track_id: str) -> list[dict]:
    t = get_track(track_id)
    return json.loads(t.candidates) if t and t.candidates else []
