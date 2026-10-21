"""MusicBrainz browsing endpoints; albums of local files (``library.local``) are answered from the files."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from sqlmodel import col, select

from ofy import artistimage, coverart
from ofy.db import Album, Track, session
from ofy.library import local
from ofy.library.status import album_summary
from ofy.mb import logic
from ofy.mb.client import MusicBrainzError, NotFound, get_mb
from ofy.tagging import writers

router = APIRouter(prefix="/api", tags=["browse"])


def track_state(t: Track | None) -> dict[str, Any]:
    if t is None:
        return {"status": "none", "lyrics_status": "none", "progress": 0, "stage": None}
    return {
        "status": t.status,
        "lyrics_status": t.lyrics_status,
        "progress": t.progress,
        "stage": t.stage,
        "error": t.error,
        "match_score": t.match_score,
        "match_source": t.match_source,
        "video_id": t.video_id,
        "file_path": t.file_path,
        "file_format": t.file_format,
    }


def release_group_states(rg_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Album status per release-group, using whichever release of the group has local tracks."""
    if not rg_ids:
        return {}
    with session() as s:
        albums = s.exec(select(Album).where(col(Album.release_group_id).in_(rg_ids))).all()
        tracks = s.exec(select(Track).where(col(Track.release_group_id).in_(rg_ids))).all()
    by_release: dict[str, list[str]] = {}
    for t in tracks:
        by_release.setdefault(t.release_id, []).append(t.status)
    out: dict[str, dict[str, Any]] = {}
    for a in albums:
        summ = album_summary(by_release.get(a.release_id, []), a.track_count)
        prev = out.get(a.release_group_id)
        if prev is None or summ["done"] > prev["done"]:
            out[a.release_group_id] = {**summ, "release_id": a.release_id}
    return out


async def _mb(coro):
    try:
        return await coro
    except NotFound as e:
        raise HTTPException(404, "Not found on MusicBrainz") from e
    except MusicBrainzError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/search")
async def search(q: str = Query(min_length=1), type: Literal["all", "artist", "album", "track"] = "all",
                 limit: int = Query(20, le=100)) -> dict[str, Any]:
    mb = get_mb()
    out: dict[str, Any] = {}
    if type in ("all", "artist"):
        data = await _mb(mb.search("artist", q, limit=limit if type == "artist" else 8))
        out["artists"] = [logic.summarize_artist(a) for a in data.get("artists", [])]
    if type in ("all", "album"):
        data = await _mb(mb.search("release-group", q, limit=limit if type == "album" else 12))
        rgs = [logic.summarize_release_group(rg) for rg in data.get("release-groups", [])]
        states = release_group_states([r["id"] for r in rgs])
        out["albums"] = [{**r, "library": states.get(r["id"])} for r in rgs]
    if type in ("all", "track"):
        data = await _mb(mb.search("recording", q, limit=limit if type == "track" else 12))
        out["tracks"] = [logic.summarize_recording_hit(r) for r in data.get("recordings", [])]
    return out


@router.get("/artist/{mbid}")
async def artist(mbid: str) -> dict[str, Any]:
    mb = get_mb()
    a = await _mb(mb.artist(mbid))
    groups = await _mb(mb.browse_release_groups(mbid))
    disco = logic.group_discography(groups)
    states = release_group_states([rg["id"] for rg in groups])
    for bucket in disco:
        for item in bucket["items"]:
            item["library"] = states.get(item["id"])
    # Artist image: newest studio album cover (MusicBrainz has no artist images).
    image_rg = next((b["items"][0]["id"] for b in disco if b["type"] == "Album"), None)
    return {
        **logic.summarize_artist(a),
        "image_release_group": image_rg,
        "wikidata_id": artistimage.wikidata_id_from_artist(a),
        "discography": disco,
        "related": logic.related_artists(a),
    }


def _local_album(release_id: str) -> tuple[Album, list[Track]]:
    with session() as s:
        album = s.get(Album, release_id)
        tracks = list(s.exec(select(Track).where(Track.release_id == release_id)).all())
    if album is None:
        raise HTTPException(404, "Not in the library")
    return album, tracks


@router.get("/release-group/{mbid}")
async def release_group(mbid: str, release: str | None = None) -> dict[str, Any]:
    if local.is_local(mbid):
        album, tracks = _local_album(mbid)
        return local.release_group_detail(album, tracks, await asyncio.to_thread(local.genres, tracks))
    mb = get_mb()
    rg = await _mb(mb.release_group(mbid))
    releases = await _mb(mb.browse_releases(mbid))
    canonical = logic.pick_canonical_release(releases)
    if canonical is None:
        raise HTTPException(404, "Release group has no releases")
    # Prefer a release the user already has locally, then an explicit choice, then canonical.
    selected = release
    if selected is None:
        with session() as s:
            owned = s.exec(select(Album).where(Album.release_group_id == mbid)).first()
        if owned and any(r["id"] == owned.release_id for r in releases):
            selected = owned.release_id
    selected = selected or canonical["id"]
    editions = sorted((logic.summarize_release(r) for r in releases),
                      key=lambda r: (r["date"] or "9999", r["title"]))
    return {
        **logic.summarize_release_group(rg),
        "genres": [g["name"] for g in sorted(rg.get("genres") or [], key=lambda g: -g.get("count", 0))][:5],
        "canonical_release_id": canonical["id"],
        "selected_release_id": selected,
        "editions": editions,
    }


@router.get("/release/{mbid}")
async def release(mbid: str) -> dict[str, Any]:
    if local.is_local(mbid):
        return _local_release(mbid)
    rel = await _mb(get_mb().release(mbid))
    rows = logic.tracklist(rel)
    ids = [r["track_id"] for r in rows]
    with session() as s:
        tracks = {t.track_id: t for t in s.exec(select(Track).where(col(Track.track_id).in_(ids))).all()}
    for r in rows:
        r["library"] = track_state(tracks.get(r["track_id"]))
    rg = rel.get("release-group") or {}
    return {
        **logic.summarize_release(rel),
        "artist": logic.artist_credit_string(rel.get("artist-credit")),
        "artist_id": (logic.artist_credit_ids(rel.get("artist-credit")) or [None])[0],
        "release_group_id": rg.get("id"),
        "release_group_title": rg.get("title"),
        "primary_type": rg.get("primary-type"),
        "first_release_date": rg.get("first-release-date"),
        "length_ms": sum(r["length_ms"] or 0 for r in rows),
        "tracks": rows,
        "library": album_summary([tracks[i].status for i in ids if i in tracks], len(rows)),
    }


def _local_release(release_id: str) -> dict[str, Any]:
    album, tracks = _local_album(release_id)
    by_id = {t.track_id: t for t in tracks}
    rows = local.tracklist(tracks)
    for r in rows:
        r["library"] = track_state(by_id[r["track_id"]])
    return {
        **local.edition(album, tracks),
        "artist": album.artist,
        "artist_id": album.artist_id,
        "release_group_id": album.release_group_id,
        "release_group_title": album.title,
        "primary_type": "Album",
        "first_release_date": album.year,
        "length_ms": sum(r["length_ms"] or 0 for r in rows),
        "tracks": rows,
        "library": album_summary([t.status for t in tracks], len(tracks)),
    }


async def _local_cover(release_id: str) -> Response:
    with session() as s:
        album = s.get(Album, release_id)
        tracks = list(s.exec(select(Track).where(Track.release_id == release_id)).all())
    data = await asyncio.to_thread(local.cover, album, tracks)
    if data is None:
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    # revalidated each time: the files' cover can change
    return Response(data, media_type=writers.image_mime(data), headers={"Cache-Control": "no-cache"})


@router.get("/cover/{kind}/{mbid}")
async def cover(kind: Literal["release", "release-group"], mbid: str,
                size: Literal["250", "500", "1200"] = "500", fallback_rg: str | None = None) -> Response:
    if local.is_local(mbid):
        return await _local_cover(mbid)
    unavailable = False
    data = None
    for k, m in ((kind, mbid), ("release-group", fallback_rg)):
        if data is not None or not m:
            continue
        try:
            data = await coverart.fetch_front(k, m, size)
        except coverart.CoverUnavailable:
            unavailable = True
    if data is None:
        if unavailable:  # may exist: don't let the browser remember the failure
            return Response(status_code=503, headers={"Cache-Control": "no-store"})
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})



@router.get("/artist-image/{mbid}")
async def artist_image(mbid: str, size: Literal["250", "500", "1200"] = "500",
                       fallback_rg: str | None = None, wikidata: str | None = None) -> Response:
    """Artist photo from Wikidata/Commons; falls back to an album cover of the artist if given.
    ``wikidata`` (the artist's Q-id, when the caller knows it) saves a Wikidata search."""
    if local.is_local(fallback_rg):
        # an artist only known from local files: the cover of one of their albums
        if local.is_local(mbid):
            return await _local_cover(fallback_rg)  # type: ignore[arg-type]
        fallback_rg = None
    elif local.is_local(mbid):
        return Response(status_code=404, headers={"Cache-Control": "no-cache"})
    if wikidata and not (wikidata.startswith("Q") and wikidata[1:].isdigit()):
        wikidata = None
    data = await artistimage.fetch_artist_image(mbid, size, wikidata)
    if data is None and fallback_rg:
        data = await coverart.front_or_none("release-group", fallback_rg, size)
    if data is None:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    media = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    return Response(data, media_type=media, headers={"Cache-Control": "public, max-age=604800"})
