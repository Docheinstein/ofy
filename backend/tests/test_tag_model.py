from ofy.tagging.mapping import model_to_fields
from ofy.tagging.model import VARIOUS_ARTISTS_ID, build_tag_model, format_genres, top_genres

RELEASE_ID = "1834eae1-741b-3c03-9ca5-0df3decb43ea"
RADIOHEAD = "a74b1b7f-71a5-4011-9441-d0b5e4122711"


def _airbag(release):
    return release["media"][0]["tracks"][0]


def test_build_from_fixture(fixture):
    rel = fixture("release_ok_computer.json")
    t = _airbag(rel)
    m = build_tag_model(rel, t["id"], youtube_video_id="jNY_wLukVW0")
    assert m.title == "Airbag"
    assert m.artist == "Radiohead" and m.artists == ["Radiohead"]
    assert m.albumartist == "Radiohead" and m.albumartistsort == "Radiohead"
    assert m.album == "OK Computer"
    assert (m.tracknumber, m.totaltracks, m.discnumber, m.totaldiscs) == (1, 12, 1, 1)
    assert m.date == "1997-05-21"
    assert m.originaldate == "1997-05-21" and m.originalyear == "1997"
    assert m.genres[0] == "alternative rock"
    assert len(m.genres) <= 5
    assert m.labels == ["EMI"]
    assert m.catalognumbers == ["TOCP-50201"]
    assert m.barcode == "4988006729254"
    assert m.isrcs[0] == "GBAYE9701274"
    assert m.media == "CD"
    assert m.releasetype == ["album"]
    assert m.releasestatus == "official"
    assert m.releasecountry == "JP"
    assert m.compilation is False
    assert m.script == "Latn" and m.language == "eng"
    assert m.length_ms == t["length"]
    assert m.musicbrainz_recordingid == t["recording"]["id"]
    assert m.musicbrainz_trackid == t["id"]
    assert m.musicbrainz_albumid == RELEASE_ID
    assert m.musicbrainz_releasegroupid == "b1392450-e666-3926-a536-22c65f834433"
    assert m.musicbrainz_artistids == [RADIOHEAD]
    assert m.musicbrainz_albumartistids == [RADIOHEAD]
    assert m.youtube_video_id == "jNY_wLukVW0"


def test_label_info_without_label(fixture):
    # MusicBrainz lists a catalog number with "label": null when the label isn't known
    rel = fixture("release_ok_computer.json")
    rel["label-info"] = [{"catalog-number": "C0", "label": None}, *rel.get("label-info", [])]
    m = build_tag_model(rel, _airbag(rel)["id"])
    assert m.labels == ["EMI"]
    assert "C0" in m.catalognumbers


def test_path_values(fixture):
    rel = fixture("release_ok_computer.json")
    m = build_tag_model(rel, _airbag(rel)["id"])
    v = m.path_values("mp3")
    assert v["albumartist"] == "Radiohead" and v["year"] == "1997" and v["track"] == 1 and v["disc"] == 1


def _synthetic_release():
    va = {"id": VARIOUS_ARTISTS_ID, "name": "Various Artists", "sort-name": "Various Artists"}
    a = {"id": "aaa", "name": "Daft Punk", "sort-name": "Daft Punk"}
    b = {"id": "bbb", "name": "Romanthony", "sort-name": "Romanthony"}
    track = lambda i, pos: {  # noqa: E731
        "id": f"t{i}", "position": pos, "number": str(pos), "title": f"Song {i}", "length": 1000 * i,
        "artist-credit": [{"name": "Daft Punk", "joinphrase": " feat. ", "artist": a},
                          {"name": "Romanthony", "joinphrase": "", "artist": b}],
        "recording": {"id": f"r{i}", "title": f"Song {i}", "isrcs": [], "genres": [{"name": "house", "count": 3}]},
    }
    return {
        "id": "rel", "title": "Comp", "status": "Official", "date": "2001", "country": "XE",
        "artist-credit": [{"name": "Various Artists", "joinphrase": "", "artist": va}],
        "release-group": {"id": "rg", "primary-type": "Album", "secondary-types": ["Compilation"],
                          "first-release-date": "2000-03-01", "genres": [{"name": "electronic", "count": 10}]},
        "label-info": [{"catalog-number": "C1", "label": {"id": "l1", "name": "Virgin"}},
                       {"catalog-number": "C2", "label": {"id": "l1", "name": "Virgin"}}],
        "media": [
            {"position": 1, "format": "CD", "track-count": 2, "tracks": [track(1, 1), track(2, 2)]},
            {"position": 2, "format": "CD", "title": "Bonus", "track-count": 1, "tracks": [track(3, 1)]},
        ],
    }


def test_multi_artist_multi_disc_compilation():
    m = build_tag_model(_synthetic_release(), "t3")
    assert m.artist == "Daft Punk feat. Romanthony"
    assert m.artists == ["Daft Punk", "Romanthony"]
    assert m.musicbrainz_artistids == ["aaa", "bbb"]
    assert m.albumartist == "Various Artists"
    assert m.compilation is True
    assert (m.discnumber, m.totaldiscs, m.tracknumber, m.totaltracks) == (2, 2, 1, 1)
    assert m.discsubtitle == "Bonus"
    assert m.releasetype == ["album", "compilation"]
    assert m.labels == ["Virgin"] and m.catalognumbers == ["C1", "C2"]
    assert m.originaldate == "2000-03-01" and m.date == "2001"
    assert m.genres == ["electronic", "house"]
    assert m.isrcs == []


def test_model_to_fields_omits_empty():
    m = build_tag_model(_synthetic_release(), "t1")
    f = model_to_fields(m)
    assert "isrc" not in f and "barcode" not in f and "lyrics" not in f
    assert f["compilation"] == ["1"]
    assert f["artists"] == ["Daft Punk", "Romanthony"]
    assert f["tracknumber"] == ["1"] and f["totaltracks"] == ["2"]


def test_top_genres_merges_and_filters_noise():
    g = top_genres([{"name": "rock", "count": 50}], [{"name": "rock", "count": 10}, {"name": "pop", "count": 2}],
                   [{"name": "indie", "count": 20}])
    assert g == ["rock", "indie"]


def test_format_genres():
    g = ["pop", "dance-pop", "synth-pop"]
    assert format_genres(g) == g
    assert format_genres(g, "joined", "; ") == ["pop; dance-pop; synth-pop"]
    assert format_genres(g, "joined", "/") == ["pop/dance-pop/synth-pop"]
    assert format_genres(g, "first") == ["pop"]
    assert format_genres([], "joined") == [] and format_genres([], "first") == []


def test_build_with_genre_mode(fixture):
    rel = fixture("release_ok_computer.json")
    t = _airbag(rel)
    multi = build_tag_model(rel, t["id"]).genres
    assert build_tag_model(rel, t["id"], genre_mode="first").genres == multi[:1]
    assert build_tag_model(rel, t["id"], genre_mode="joined", genre_separator=";").genres == [";".join(multi)]
