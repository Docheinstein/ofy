import asyncio
import shutil
from pathlib import Path

import pytest
from fastapi import HTTPException
from mutagen.id3 import APIC, ID3, TALB, TCON, TDRC, TIT2, TPE1, TRCK, PictureType
from sqlmodel import select
from test_tag_writers import TINY_JPEG, make_audio

from ofy.config import Settings
from ofy.db import Album, SyncSelection, Track, save_settings, session
from ofy.library import local
from ofy.library.local import LocalFile, plan_local
from ofy.library.scanner import scan_library

ROOT = Path("/music")


def lf(rel: str, **tags: str) -> LocalFile:
    return LocalFile(str(ROOT / rel), rel, "mp3", "none", {k: [v] for k, v in tags.items()}, 1000)


def test_files_group_by_folder_and_album_tag():
    albums, tracks = plan_local([
        lf("OST/a.mp3", album="Zelda", artist="Koji Kondo", tracknumber="2", title="Two"),
        lf("OST/b.mp3", album="Zelda", artist="Koji Kondo", tracknumber="1", title="One"),
        lf("OST/c.mp3", album="Mario", artist="Koji Kondo"),
        lf("Other/d.mp3", album="Zelda", artist="Koji Kondo"),
    ], ROOT, {})
    assert sorted((a.title, a.track_count) for a in albums) == [("Mario", 1), ("Zelda", 1), ("Zelda", 2)]
    zelda = next(a for a in albums if a.track_count == 2)
    assert zelda.folder == "/music/OST" and zelda.artist == "Koji Kondo"
    assert [(t.position, t.title) for t in tracks if t.release_id == zelda.release_id] == [(1, "One"), (2, "Two")]
    assert all(local.is_local(x) for x in [zelda.release_id, zelda.artist_id, tracks[0].track_id])


def test_ids_are_stable():
    files = [lf("OST/a.mp3", album="Zelda", artist="Koji Kondo")]
    assert plan_local(files, ROOT, {}) == plan_local(files, ROOT, {})


def test_missing_tags_fall_back_to_folder_and_file_names():
    albums, tracks = plan_local([lf("Game Rips/02 Boss.mp3"), lf("Game Rips/01 Title.mp3", tracknumber="7"),
                                 lf("loose.mp3")], ROOT, {})
    rips = next(a for a in albums if a.title == "Game Rips")
    assert rips.artist == "Unknown artist" and rips.year is None
    # untagged numbers continue after the tagged ones
    assert [(t.position, t.title) for t in tracks if t.release_id == rips.release_id] == [(7, "01 Title"), (8, "02 Boss")]
    assert next(a for a in albums if a.release_id != rips.release_id).title == "Unknown album"


def test_album_artist_and_year():
    albums, _ = plan_local([lf("V/a.mp3", album="V", artist="A", date="2001-05-02"),
                            lf("V/b.mp3", album="V", artist="B")], ROOT, {})
    assert (albums[0].artist, albums[0].year) == ("Various Artists", "2001")
    albums, _ = plan_local([lf("V/a.mp3", album="V", artist="A", albumartist="Band")], ROOT, {})
    assert albums[0].artist == "Band"


def test_artist_already_in_the_library_is_reused():
    albums, _ = plan_local([lf("X/a.mp3", album="X", artist="Radiohead")], ROOT, {"radiohead": "mbid-radiohead"})
    assert albums[0].artist_id == "mbid-radiohead"


def test_lyrics_status():
    assert local.lyrics_status("none", "synced") == "synced"
    assert local.lyrics_status("synced", "none") == "none"
    assert local.lyrics_status("not_found", "none") == "not_found"
    assert local.lyrics_status("not_found", "plain") == "plain"


# --- scanning real files ----------------------------------------------------------------------------

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


def tagged_mp3(tmp_path: Path, dest: Path, *, title: str, track: str, cover: bool = False) -> Path:
    src = make_audio(tmp_path, "mp3")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(src, dest)
    tags = ID3()
    tags.add(TIT2(text=title))
    tags.add(TPE1(text="Koji Kondo"))
    tags.add(TALB(text="Ocarina of Time"))
    tags.add(TRCK(text=track))
    tags.add(TDRC(text="1998"))
    tags.add(TCON(text="Soundtrack"))
    if cover:
        tags.add(APIC(mime="image/jpeg", type=PictureType.COVER_FRONT, data=TINY_JPEG))
    tags.save(dest)
    return dest


@pytest.fixture
def library(tmp_db, tmp_path):
    lib = tmp_path / "lib"
    save_settings(Settings(library_path=str(lib)))
    a = tagged_mp3(tmp_path, lib / "OoT" / "a.mp3", title="Title Theme", track="1", cover=True)
    b = tagged_mp3(tmp_path, lib / "OoT" / "b.mp3", title="Kokiri Forest", track="2")
    return lib, a, b


def _rows():
    with session() as s:
        return list(s.exec(select(Album)).all()), list(s.exec(select(Track)).all())


@needs_ffmpeg
def test_scan_adds_files_without_musicbrainz_ids(library):
    result = scan_library()
    assert result.local_changes == 3  # one album, two tracks
    (album,), tracks = _rows()
    assert (album.title, album.artist, album.year, album.track_count) == ("Ocarina of Time", "Koji Kondo", "1998", 2)
    assert sorted((t.position, t.title, t.status) for t in tracks) == [(1, "Title Theme", "done"), (2, "Kokiri Forest", "done")]
    assert all(t.recording_id == t.track_id and t.length_ms for t in tracks)
    assert scan_library().local_changes == 0  # nothing changed on disk


@needs_ffmpeg
def test_album_page_and_cover(library):
    from ofy.api.browse import _local_release, release_group

    scan_library()
    (album,), tracks = _rows()
    rel = _local_release(album.release_id)
    assert [t["title"] for t in rel["tracks"]] == ["Title Theme", "Kokiri Forest"]
    assert rel["library"]["status"] == "complete" and rel["formats"] == ["MP3"]
    rg = asyncio.run(release_group(album.release_id))
    assert rg["genres"] == ["Soundtrack"] and rg["selected_release_id"] == album.release_id
    assert local.cover(album, tracks) == TINY_JPEG


@needs_ffmpeg
def test_artist_image_falls_back_to_first_album_with_a_cover(library, monkeypatch):
    from ofy.api import browse

    scan_library()
    (album,), _ = _rows()
    with session() as s:  # an earlier album of theirs whose files have no cover
        s.add(Album(release_id="r-old", release_group_id="rg-old", title="Old", artist=album.artist,
                    artist_id=album.artist_id, year="1980"))
        s.commit()
    r = asyncio.run(browse.artist_image(album.artist_id))  # type: ignore[arg-type]
    assert r.body == TINY_JPEG and r.headers["cache-control"] == "no-cache"

    async def no_photo(*_):
        return None

    monkeypatch.setattr(browse.artistimage, "fetch_artist_image", no_photo)
    with session() as s:  # the same for an artist known to MusicBrainz without a photo
        for a in s.exec(select(Album)).all():
            a.artist_id = "mb-artist"
            s.add(a)
        s.commit()
    assert asyncio.run(browse.artist_image("mb-artist")).body == TINY_JPEG
    assert asyncio.run(browse.artist_image("someone-else")).status_code == 404

    async def online(*_):
        raise AssertionError("looked online")

    monkeypatch.setattr(browse.artistimage, "fetch_artist_image", online)
    monkeypatch.setattr(browse.coverart, "front_or_none", online)
    assert asyncio.run(browse.artist_image("mb-artist", library=True)).body == TINY_JPEG
    assert asyncio.run(browse.artist_image("someone-else", fallback_rg="rg", library=True)).status_code == 404


@needs_ffmpeg
def test_edited_and_deleted_files_follow(library):
    _, a, b = library
    scan_library()
    tags = ID3(b)
    tags.add(TIT2(text="Kokiri Forest (Remix)"))
    tags.save(b)
    a.unlink()
    scan_library()
    (album,), tracks = _rows()
    assert [t.title for t in tracks] == ["Kokiri Forest (Remix)"] and album.track_count == 1
    b.unlink()
    scan_library()
    assert _rows() == ([], [])


@needs_ffmpeg
def test_local_album_is_synced(library):
    from ofy.sync import build_plan

    lib, *_ = library
    scan_library()
    (album,), _ = _rows()
    with session() as s:
        s.add(SyncSelection(kind="album", ref_id=album.release_id))
        s.commit()
    plan = build_plan(lib)
    assert sorted(str(rel) for rel, _ in plan.files) == ["OoT/a.mp3", "OoT/b.mp3"]


def test_musicbrainz_actions_refused():
    from ofy.api.actions import retag

    with pytest.raises(HTTPException) as e:
        retag("local-album-123")
    assert e.value.status_code == 400


@needs_ffmpeg
@pytest.mark.parametrize("unplugged", ["gone", "empty"])
def test_missing_library_is_left_alone(library, unplugged):
    from ofy.api.actions import library_status

    lib, *_ = library
    scan_library()
    before = _rows()
    shutil.rmtree(lib)
    if unplugged == "empty":
        lib.mkdir()  # an empty mount point
    assert scan_library().missing
    assert _rows() == before
    assert asyncio.run(library_status())["available"] is False


def test_empty_library_is_not_missing(tmp_db, tmp_path):
    from ofy.api.actions import library_status

    save_settings(Settings(library_path=str(tmp_path / "nothing-yet")))
    assert not scan_library().missing
    assert asyncio.run(library_status())["available"] is True
