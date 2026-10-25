"""Library files without MusicBrainz ids ("local" files), shown from their own tags.

The rest of the library is keyed on MusicBrainz ids; these files get ids of their own, prefixed with
``local-``: a track's comes from its path in the library, an album's from its folder and album tag, so
files that sit together and share an album tag make one album. They are read again on every scan, so
tags edited here or in another tagger show up on the next one.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from ofy.db import Album, Track

PREFIX = "local-"
COVER_FILES = ("cover", "folder", "front", "album")
COVER_EXTS = (".jpg", ".jpeg", ".png")


def is_local(mbid: str | None) -> bool:
    return bool(mbid) and mbid.startswith(PREFIX)  # type: ignore[union-attr]


def _id(kind: str, key: str) -> str:
    return f"{PREFIX}{kind}-{hashlib.sha1(key.encode()).hexdigest()[:20]}"


def artist_id_for(name: str) -> str:
    return _id("artist", name.casefold())


@dataclass
class LocalFile:
    path: str
    rel: str  # relative to the library folder, "/"-separated
    fmt: str
    lyrics: str  # synced (.lrc sidecar) | plain (embedded) | instrumental | not_found (noted in the tags) | none
    tags: dict[str, list[str]]
    length_ms: int | None = None


@dataclass
class LocalTrack:
    track_id: str
    release_id: str
    disc: int
    position: int
    title: str
    artist: str
    length_ms: int | None
    file_path: str
    file_format: str
    lyrics: str


@dataclass
class LocalAlbum:
    release_id: str
    title: str
    artist: str
    artist_id: str
    year: str | None
    track_count: int
    folder: str


def _first(tags: dict[str, list[str]], k: str) -> str:
    v = [x.strip() for x in tags.get(k) or [] if x.strip()]
    return v[0] if v else ""


def _num(tags: dict[str, list[str]], k: str) -> int | None:
    v = _first(tags, k).partition("/")[0]
    return int(v) if v.isdigit() else None


def _album_artist(files: list[LocalFile]) -> str:
    for f in files:
        if a := _first(f.tags, "albumartist"):
            return a
    artists = Counter(a for f in files if (a := _first(f.tags, "artist")))
    if len(artists) == 1:
        return next(iter(artists))
    return "Various Artists" if artists else "Unknown artist"


def _year(files: list[LocalFile]) -> str | None:
    for k in ("originalyear", "originaldate", "date"):
        for f in files:
            y = _first(f.tags, k)[:4]
            if y.isdigit():
                return y
    return None


def plan_local(files: list[LocalFile], root: Path, known_artists: dict[str, str]) -> tuple[list[LocalAlbum], list[LocalTrack]]:
    """Group the files into albums (same folder and album tag) and number their tracks.

    ``known_artists`` maps casefolded names to MusicBrainz artist ids already in the library, so an
    artist known there gets these albums too (artist page, artist-wide sync) rather than a second entry.
    """
    groups: dict[tuple[str, str], list[LocalFile]] = {}
    for f in files:
        folder = str(PurePosixPath(f.rel).parent)
        groups.setdefault((folder, _first(f.tags, "album").casefold()), []).append(f)
    albums: list[LocalAlbum] = []
    tracks: list[LocalTrack] = []
    for (folder, album_key), group in sorted(groups.items()):
        release_id = _id("album", f"{folder}\0{album_key}")
        group.sort(key=lambda f: (_num(f.tags, "discnumber") or 1, _num(f.tags, "tracknumber") or 10**6, f.rel))
        artist = _album_artist(group)
        title = _first(group[0].tags, "album") or (PurePosixPath(folder).name if folder != "." else "Unknown album")
        albums.append(LocalAlbum(
            release_id=release_id, title=title, artist=artist,
            artist_id=known_artists.get(artist.casefold()) or artist_id_for(artist),
            year=_year(group), track_count=len(group), folder=str(root / folder),
        ))
        # untagged numbers continue after the highest tagged one of their disc, in file name order
        last: dict[int, int] = {}
        for f in group:
            disc = _num(f.tags, "discnumber") or 1
            pos = _num(f.tags, "tracknumber") or last.get(disc, 0) + 1
            last[disc] = max(last.get(disc, 0), pos)
            tracks.append(LocalTrack(
                track_id=_id("track", f.rel), release_id=release_id, disc=disc, position=pos,
                title=_first(f.tags, "title") or PurePosixPath(f.rel).stem,
                artist=_first(f.tags, "artist") or artist,
                length_ms=f.length_ms, file_path=f.path, file_format=f.fmt, lyrics=f.lyrics,
            ))
    return albums, tracks


def lyrics_status(previous: str, on_disk: str) -> str:
    """What's on disk wins; without anything keep a looked-up 'instrumental'/'not found'."""
    if on_disk != "none":
        return on_disk
    return previous if previous in ("instrumental", "not_found") else "none"


# --- album page -------------------------------------------------------------------------------------

def edition(album: Album, tracks: list[Track]) -> dict[str, Any]:
    """The album as its one 'edition', shaped like a summarized MusicBrainz release."""
    formats = sorted({(t.file_format or "").upper() for t in tracks if t.file_format})
    return {
        "id": album.release_id, "title": album.title, "status": None, "date": album.year, "country": None,
        "formats": formats, "track_count": len(tracks), "disambiguation": None, "barcode": None,
        "labels": [], "catalog_numbers": [],
    }


def release_group_detail(album: Album, tracks: list[Track], genres: list[str]) -> dict[str, Any]:
    return {
        "id": album.release_id, "title": album.title, "primary_type": "Album", "secondary_types": [],
        "first_release_date": album.year, "year": album.year, "artist": album.artist, "artist_id": album.artist_id,
        "genres": genres, "canonical_release_id": album.release_id, "selected_release_id": album.release_id,
        "editions": [edition(album, tracks)],
    }


def tracklist(tracks: list[Track]) -> list[dict[str, Any]]:
    """Rows shaped like ``mb.logic.tracklist``'s."""
    discs = Counter(t.disc for t in tracks)
    return [{
        "track_id": t.track_id, "recording_id": t.recording_id, "disc": t.disc, "disc_total": len(discs),
        "position": t.position, "number": str(t.position), "track_total": discs[t.disc], "title": t.title,
        "artist": t.artist, "length_ms": t.length_ms, "isrcs": [], "medium_format": None, "medium_title": None,
    } for t in sorted(tracks, key=lambda t: (t.disc, t.position))]


def cover(album: Album | None, tracks: list[Track]) -> bytes | None:
    """The first cover embedded in the album's files, else a cover image next to them."""
    from ofy.tagging import writers

    for t in sorted(tracks, key=lambda t: (t.disc, t.position)):
        if t.file_path and Path(t.file_path).is_file():
            try:
                data = writers.read_cover(Path(t.file_path))
            except Exception:
                data = None
            if data:
                return data
    if album and album.folder and Path(album.folder).is_dir():
        for p in sorted(Path(album.folder).iterdir()):
            if p.stem.lower() in COVER_FILES and p.suffix.lower() in COVER_EXTS and p.is_file():
                return p.read_bytes()
    return None


def genres(tracks: list[Track]) -> list[str]:
    from ofy.tagging import writers

    for t in tracks:
        if t.file_path and Path(t.file_path).is_file():
            try:
                values = writers.read_fields(Path(t.file_path)).get("genre") or []
            except Exception:
                continue
            if values:
                return [v for v in values if v.strip()][:5]
    return []
