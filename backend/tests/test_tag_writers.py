import shutil
import subprocess
from pathlib import Path

import pytest
from mutagen.id3 import ID3

from ofy.tagging import writers
from ofy.tagging.mapping import lyrics_missing_from, model_to_fields
from ofy.tagging.model import build_tag_model

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")

# 1x1 white JPEG
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c"
    "20242e2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc0000b080001000101011100ffc4001f00000105010101010101"
    "00000000000000000102030405060708090a0bffc400b5100002010303020403050504040000017d01020300041105122131410613516107227114"
    "328191a1082342b1c11552d1f02433627282090a161718191a25262728292a3435363738393a434445464748494a535455565758595a6364656667"
    "68696a737475767778797a838485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5c6c7c8c9cad2d3d4d5"
    "d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffda0008010100003f00fbd3ffd9"
)

CODECS = {
    "mp3": ["-c:a", "libmp3lame", "-b:a", "64k"],
    "m4a": ["-c:a", "aac", "-b:a", "64k", "-f", "ipod"],
    "opus": ["-c:a", "libopus", "-b:a", "32k", "-f", "opus"],
}


def make_audio(tmp_path: Path, ext: str) -> Path:
    out = tmp_path / f"tone.{ext}"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         *CODECS[ext], str(out)],
        check=True,
    )
    return out


@pytest.fixture
def model(fixture):
    rel = fixture("release_ok_computer.json")
    m = build_tag_model(rel, rel["media"][0]["tracks"][0]["id"], youtube_video_id="jNY_wLukVW0")
    m.lyrics = "In the next world war\nIn a jackknifed juggernaut"
    return m


@pytest.mark.parametrize("ext", ["mp3", "m4a", "opus"])
def test_round_trip(tmp_path, model, ext):
    path = make_audio(tmp_path, ext)
    writers.write_tags(path, model, TINY_JPEG)
    got = writers.read_fields(path)
    expected = model_to_fields(model)
    for name, values in expected.items():
        assert got.get(name) == values, (ext, name, got.get(name), values)
    assert got["~cover"] == ["front"]
    ids = writers.read_mbids(path)
    assert ids["recording_id"] == model.musicbrainz_recordingid
    assert ids["track_id"] == model.musicbrainz_trackid
    assert ids["release_id"] == model.musicbrainz_albumid
    assert ids["youtube_video_id"] == "jNY_wLukVW0"
    assert writers.audio_length(path) == pytest.approx(1.0, abs=0.2)


def test_id3_specifics(tmp_path, model):
    path = make_audio(tmp_path, "mp3")
    writers.write_tags(path, model, TINY_JPEG)
    tags = ID3(path)
    assert tags.version == (2, 4, 0)
    assert tags["UFID:http://musicbrainz.org"].data.decode() == model.musicbrainz_recordingid
    assert str(tags["TXXX:MusicBrainz Album Id"]) == model.musicbrainz_albumid
    assert str(tags["TXXX:MusicBrainz Release Track Id"]) == model.musicbrainz_trackid
    assert str(tags["TRCK"]) == "1/12" and str(tags["TPOS"]) == "1/1"
    apic = tags.getall("APIC")[0]
    assert apic.type == 3 and apic.mime == "image/jpeg"
    assert tags.getall("USLT")[0].text.startswith("In the next world war")
    assert str(tags["TXXX:YOUTUBE_VIDEO_ID"]) == "jNY_wLukVW0"


def test_mp4_specifics(tmp_path, model):
    from mutagen.mp4 import MP4

    path = make_audio(tmp_path, "m4a")
    writers.write_tags(path, model, TINY_JPEG)
    f = MP4(path)
    assert f.tags["trkn"] == [(1, 12)]
    assert f.tags["----:com.apple.iTunes:MusicBrainz Track Id"][0].decode() == model.musicbrainz_recordingid
    assert f.tags["covr"][0] == TINY_JPEG
    assert f.tags["\xa9lyr"][0].startswith("In the next")


def test_vorbis_specifics(tmp_path, model):
    from mutagen.oggopus import OggOpus

    path = make_audio(tmp_path, "opus")
    writers.write_tags(path, model, TINY_JPEG)
    f = OggOpus(path)
    assert f.tags["MUSICBRAINZ_TRACKID"] == [model.musicbrainz_recordingid]
    assert f.tags["MUSICBRAINZ_RELEASETRACKID"] == [model.musicbrainz_trackid]
    assert f.tags["TRACKTOTAL"] == ["12"]
    assert "METADATA_BLOCK_PICTURE" in f.tags


@pytest.mark.parametrize("ext", ["mp3", "m4a", "opus"])
def test_rewrite_replaces_old_tags_and_set_lyrics(tmp_path, model, ext):
    path = make_audio(tmp_path, ext)
    writers.write_tags(path, model, TINY_JPEG)
    model.title = "Airbag (corrected)"
    model.lyrics = None
    writers.write_tags(path, model, None)
    got = writers.read_fields(path)
    assert got["title"] == ["Airbag (corrected)"]
    assert "lyrics" not in got and "~cover" not in got
    writers.set_lyrics(path, "La la")
    assert writers.get_lyrics(path) == "La la"
    assert writers.read_fields(path)["title"] == ["Airbag (corrected)"]
    writers.set_lyrics(path, None)
    assert writers.get_lyrics(path) is None


@pytest.mark.parametrize("ext", ["mp3", "m4a", "opus"])
def test_lyrics_missing_note_survives_a_retag(tmp_path, model, ext):
    path = make_audio(tmp_path, ext)
    writers.write_tags(path, model, None)
    writers.set_lyrics_missing(path, "instrumental")
    got = writers.read_fields(path)
    assert got["haslyrics"] == ["0"] and got["instrumental"] == ["1"] and got["title"] == ["Airbag"]
    assert lyrics_missing_from(got) == "instrumental"
    assert "haslyrics" not in writers.EDITABLE and "instrumental" not in writers.EDITABLE
    writers.set_lyrics_missing(path, "not_found")
    got = writers.read_fields(path)
    assert "instrumental" not in got and lyrics_missing_from(got) == "not_found"
    model.lyrics_missing = lyrics_missing_from(got)  # what a retag carries over
    writers.write_tags(path, model, None)
    assert lyrics_missing_from(writers.read_fields(path)) == "not_found"
    writers.set_lyrics_missing(path, None)
    got = writers.read_fields(path)
    assert "haslyrics" not in got and lyrics_missing_from(got) is None


def test_multi_value_fields(tmp_path, model):
    model.artists = ["Daft Punk", "Romanthony"]
    model.musicbrainz_artistids = ["a", "b"]
    model.genres = ["house", "electronic"]
    for ext in ("mp3", "m4a", "opus"):
        path = make_audio(tmp_path, ext)
        writers.write_tags(path, model, None)
        got = writers.read_fields(path)
        assert got["artists"] == ["Daft Punk", "Romanthony"], ext
        assert got["musicbrainz_artistid"] == ["a", "b"], ext
        assert got["genre"] == ["house", "electronic"], ext


def test_jpeg_size():
    assert writers.jpeg_size(TINY_JPEG) == (1, 1)


@pytest.mark.parametrize("ext", ["mp3", "m4a", "opus"])
def test_edit_fields(tmp_path, model, ext):
    path = make_audio(tmp_path, ext)
    writers.write_tags(path, model, TINY_JPEG)
    before = writers.read_fields(path)
    writers.edit_fields(path, {
        "title": ["Airbag (Remastered)"],          # edit
        "genre": ["Rock", "Alternative"],          # add, multi-valued
        "isrc": [],                                # remove
        "totaltracks": ["13"],                     # half of TRCK / trkn
        "musicbrainz_albumid": ["  "],             # blank counts as removal
    })
    got = writers.read_fields(path)
    assert got["title"] == ["Airbag (Remastered)"]
    assert got["genre"] == ["Rock", "Alternative"]
    assert "isrc" not in got and "musicbrainz_albumid" not in got
    assert got["tracknumber"] == before["tracknumber"] and got["totaltracks"] == ["13"]
    # untouched: other tags, lyrics and the cover
    assert got["album"] == before["album"]
    assert got["musicbrainz_recordingid"] == before["musicbrainz_recordingid"]
    assert got["lyrics"] == before["lyrics"]
    assert got["~cover"] == ["front"]

    writers.edit_fields(path, {"tracknumber": [], "totaltracks": [], "musicbrainz_recordingid": []})
    got = writers.read_fields(path)
    assert "tracknumber" not in got and "totaltracks" not in got and "musicbrainz_recordingid" not in got


@pytest.mark.parametrize("changes", [
    {"lyrics": ["la la"]},
    {"made_up": ["x"]},
    {"tracknumber": ["two"]},
    {"discnumber": ["1", "2"]},
    {"compilation": ["yes"]},
])
def test_edit_fields_rejects(tmp_path, model, changes):
    path = make_audio(tmp_path, "mp3")
    writers.write_tags(path, model, TINY_JPEG)
    with pytest.raises(ValueError):
        writers.edit_fields(path, changes)


def test_edit_fields_total_needs_number(tmp_path, model):
    path = make_audio(tmp_path, "opus")
    writers.write_tags(path, model, TINY_JPEG)
    with pytest.raises(ValueError):
        writers.edit_fields(path, {"tracknumber": [], "totaltracks": ["12"]})
