"""Refresh tags rewrites tags from fresh MusicBrainz data without touching YouTube or the audio."""

import hashlib
import shutil
import subprocess

import pytest

from ofy import pipeline
from ofy.config import Settings
from ofy.db import Album, Job, Track, save_settings, session
from ofy.tagging import writers
from ofy.tagging.model import build_tag_model

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")


def audio_md5(path):
    out = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(path), "-map", "0:a", "-c", "copy", "-f", "md5", "-"],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


class FakeMB:
    def __init__(self, release):
        self.release_json = release
        self.calls = []

    async def release(self, mbid, fresh=False):
        self.calls.append((mbid, fresh))
        return self.release_json


async def test_retag_without_youtube(tmp_db, tmp_path, fixture, monkeypatch):
    release = fixture("release_ok_computer.json")
    t0 = release["media"][0]["tracks"][0]
    lib = tmp_path / "lib"
    save_settings(Settings(library_path=str(lib)))
    model = build_tag_model(release, t0["id"], youtube_video_id="jNY_wLukVW0")
    dest = pipeline.library_destination(Settings(library_path=str(lib)), model, "mp3", t0["id"])
    dest.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame",
                    str(dest)], check=True)
    model.title = "Stale title"
    writers.write_tags(dest, model, None)
    before = audio_md5(dest)

    with session() as s:
        s.add(Album(release_id=release["id"], release_group_id=release["release-group"]["id"], title="x", artist="y",
                    track_count=12))
        s.add(Track(track_id=t0["id"], recording_id=t0["recording"]["id"], release_id=release["id"],
                    release_group_id=release["release-group"]["id"], status="done", file_path=str(dest),
                    file_format="mp3", video_id="jNY_wLukVW0"))
        s.commit()

    fake = FakeMB(release)
    monkeypatch.setattr(pipeline, "get_mb", lambda: fake)

    async def no_cover(*a, **k):
        return None

    monkeypatch.setattr(pipeline.coverart, "front_for_release", no_cover)

    def boom(*a, **k):
        raise AssertionError("YouTube must not be contacted during retag")

    monkeypatch.setattr(pipeline, "download_audio", boom)
    monkeypatch.setattr(pipeline, "match_release", boom)

    await pipeline.handle_retag(Job(kind="retag", release_id=release["id"]))

    assert fake.calls == [(release["id"], True)]  # fresh MusicBrainz data
    fields = writers.read_fields(dest)
    assert fields["title"] == ["Airbag"]
    assert fields["youtube_video_id"] == ["jNY_wLukVW0"]
    assert audio_md5(dest) == before


def test_same_name_gets_disc_track_suffix(tmp_path, fixture):
    release = fixture("release_ok_computer.json")
    t1, t2 = release["media"][0]["tracks"][:2]
    settings = Settings(library_path=str(tmp_path))
    m1 = build_tag_model(release, t1["id"])
    m2 = build_tag_model(release, t2["id"])
    m2.title = m1.title  # same artist + title -> same default file name
    first = pipeline.library_destination(settings, m1, "mp3", t1["id"])
    first.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=duration=1", "-c:a", "libmp3lame",
                    str(first)], check=True)
    writers.write_tags(first, m1, None)
    assert first.name == "Radiohead - Airbag.mp3"
    second = pipeline.library_destination(settings, m2, "mp3", t2["id"])
    assert second.name == "Radiohead - Airbag (1-02).mp3"
    # the track that owns the file keeps its name
    assert pipeline.library_destination(settings, m1, "mp3", t1["id"]) == first


def test_album_joins_the_library_folder_of_its_artist(tmp_path, fixture):
    release = fixture("release_ok_computer.json")
    t0 = release["media"][0]["tracks"][0]
    lib = tmp_path / "lib"
    (lib / "The Radiohead").mkdir(parents=True)
    settings = Settings(library_path=str(lib))
    model = build_tag_model(release, t0["id"])
    pipeline.use_library_artist(model, settings)
    assert (model.albumartist, model.artist) == ("The Radiohead", "The Radiohead")
    assert model.albumartists == model.artists == ["The Radiohead"]
    dest = pipeline.library_destination(settings, model, "mp3", t0["id"])
    assert dest == lib / "The Radiohead" / "OK Computer" / "The Radiohead - Airbag.mp3"


def test_track_credit_spelled_differently_follows_the_album_artist(tmp_path, fixture):
    release = fixture("release_ok_computer.json")
    t0 = release["media"][0]["tracks"][0]
    (tmp_path / "radiohead").mkdir()
    model = build_tag_model(release, t0["id"])
    model.artist, model.artists = "RadioHead feat. Someone", ["RadioHead", "Someone"]
    pipeline.use_library_artist(model, Settings(library_path=str(tmp_path)))
    assert model.artist == "radiohead feat. Someone"
    assert model.artists == ["radiohead", "Someone"]
