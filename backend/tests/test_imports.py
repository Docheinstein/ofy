"""Songs put into an album's folder by hand are matched to its missing tracks and tagged like downloads."""

import shutil
import subprocess
from pathlib import Path

import pytest
from sqlmodel import select

from ofy import pipeline
from ofy.config import Settings
from ofy.db import Album, Job, Track, save_settings, session
from ofy.library import imports
from ofy.library.imports import AddedFile, match_files
from ofy.tagging import writers
from ofy.tracks import ensure_release_rows


def rows(*specs):
    return [{"track_id": tid, "title": title, "length_ms": length} for tid, title, length in specs]


def test_match_by_title_ignores_decorations():
    files = [AddedFile(Path("/a/Radiohead - Airbag (Remastered).mp3"), "Airbag (Remastered)", length_ms=284_000),
             AddedFile(Path("/a/x.mp3"), "Paranoid Android", length_ms=None)]
    matched, rest = match_files(files, rows(("t1", "Airbag", 284_500), ("t2", "Paranoid Android", 383_000)))
    assert matched["t1"].title == "Airbag (Remastered)" and matched["t2"].title == "Paranoid Android"
    assert rest == []


def test_match_by_musicbrainz_id_first():
    f = AddedFile(Path("/a/whatever.mp3"), "Something else", track_id="t2")
    matched, rest = match_files([f], rows(("t1", "Airbag", None), ("t2", "Paranoid Android", None)))
    assert matched == {"t2": f} and rest == []


def test_another_recording_or_song_is_left_over():
    live = AddedFile(Path("/a/live.mp3"), "Airbag", length_ms=400_000)  # 2 minutes longer: not this recording
    other = AddedFile(Path("/a/other.mp3"), "Creep", length_ms=238_000)
    matched, rest = match_files([live, other], rows(("t1", "Airbag", 284_000)))
    assert matched == {} and rest == [live, other]


def test_a_remix_is_not_the_original():
    original = AddedFile(Path("/a/Somebody to Love.mp3"), "Somebody to Love", length_ms=297_000)
    remix = rows(("t12", "Somebody to Love (1991 remix by Randy Badazz)", 300_000))
    assert match_files([original], remix) == ({}, [original])
    live = AddedFile(Path("/a/x.mp3"), "Airbag (Live)", length_ms=284_000)
    assert match_files([live], rows(("t1", "Airbag", 284_000)))[0] == {}


def test_same_title_twice_goes_to_the_closer_length():
    short = AddedFile(Path("/a/1.mp3"), "Intro", length_ms=60_000)
    long = AddedFile(Path("/a/2.mp3"), "Intro", length_ms=80_000)
    matched, _ = match_files([long, short], rows(("t1", "Intro", 61_000), ("t2", "Intro", 79_000)))
    assert matched["t1"] is short and matched["t2"] is long


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
async def test_import_release_tags_and_names_added_songs(tmp_db, tmp_path, fixture, monkeypatch):
    release = fixture("release_ok_computer.json")
    for t in release["media"][0]["tracks"]:  # the test files are 1 s long
        t["length"] = None
        t["recording"]["length"] = None
    airbag, android = release["media"][0]["tracks"][:2]
    lib = tmp_path / "lib"
    save_settings(Settings(library_path=str(lib), lyrics_fetch=True))
    ensure_release_rows(release)
    folder = lib / "Radiohead" / "OK Computer"
    folder.mkdir(parents=True)

    def mp3(name, title):
        p = folder / name
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame",
                        "-metadata", f"title={title}", "-metadata", "artist=radiohead", str(p)], check=True)
        return p

    mp3("01 airbag.mp3", "Airbag")
    mp3("Paranoid Android.mp3", "")  # no title tag: the file name tells
    mp3("Creep.mp3", "Creep")
    # a scan already took the first one for a song without MusicBrainz ids
    with session() as s:
        s.add(Album(release_id="local-a", release_group_id="local-a", title="OK Computer", artist="radiohead",
                    folder=str(folder)))
        s.add(Track(track_id="local-t", recording_id="local-t", release_id="local-a", release_group_id="local-a",
                    status="done", file_path=str(folder / "01 airbag.mp3")))
        s.commit()

    class FakeMB:
        async def release(self, mbid, fresh=False):
            return release

    async def no_cover(*a, **k):
        return None

    monkeypatch.setattr(imports, "get_mb", lambda: FakeMB())
    monkeypatch.setattr(pipeline.coverart, "front_for_release", no_cover)
    monkeypatch.setattr(pipeline.artistimage, "prefetch_artist_image", no_cover)

    result = await imports.import_release(release["id"])

    assert sorted(result["imported"]) == ["Airbag", "Paranoid Android"]
    assert result["unmatched"] == ["Creep.mp3"] and result["failed"] == []
    with session() as s:
        a, p = s.get(Track, airbag["id"]), s.get(Track, android["id"])
        assert a.status == p.status == "done" and a.file_format == "mp3"
        assert s.get(Track, "local-t") is None and s.get(Album, "local-a") is None
        lyrics_jobs = {j.track_id for j in s.exec(select(Job).where(Job.kind == "lyrics"))}
    assert Path(a.file_path).name == "Radiohead - Airbag.mp3"
    assert not (folder / "01 airbag.mp3").exists() and (folder / "Creep.mp3").exists()
    fields = writers.read_fields(Path(p.file_path))
    assert fields["title"] == ["Paranoid Android"] and fields["musicbrainz_trackid"] == [android["id"]]
    assert lyrics_jobs == {airbag["id"], android["id"]}
