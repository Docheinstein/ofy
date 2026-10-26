import httpx
import pytest

from ofy.config import Settings
from ofy.lyrics import client as lyrics_client
from ofy.lyrics import select
from ofy.lyrics.service import LyricsOutcome, fetch_for_model, write_sidecar
from ofy.tagging.model import TagModel

SYNCED = ("[00:24.24]In the next world war\n[00:32.39]In a jackknifed juggernaut\n[00:36.87]I am born again\n"
          "[00:44.10]In the neon sign\n[00:51.62]Scrolling up and down")
PLAIN = "In the next world war\nIn a jackknifed juggernaut\nI am born again\nIn the neon sign\nScrolling up and down"
AUDIO_S = 284.4  # real length of the downloaded file


def rec(**kw):
    base = {"id": 1, "trackName": "Airbag", "artistName": "Radiohead", "albumName": "OK Computer",
            "duration": 284.0, "instrumental": False, "plainLyrics": PLAIN, "syncedLyrics": SYNCED}
    base.update(kw)
    return base


def model(**kw):
    m = TagModel(title="Airbag", artist="Radiohead", artists=["Radiohead"], artistsort="Radiohead",
                 album="OK Computer", albumartist="Radiohead", albumartists=["Radiohead"],
                 albumartistsort="Radiohead", tracknumber=1, totaltracks=12, discnumber=1, totaldiscs=1,
                 length_ms=284_400)
    for k, v in kw.items():
        setattr(m, k, v)
    return m


# --- selection ---------------------------------------------------------------------------

def test_select_within_duration_tolerance():
    results = [rec(id=1, duration=290.0), rec(id=2, duration=285.5), rec(id=3, duration=283.0)]
    best = select.select_search_result(results, "Airbag", "Radiohead", 284)
    assert best["id"] in (2, 3)
    assert select.select_search_result([rec(duration=287.0)], "Airbag", "Radiohead", 284) is None


def test_select_requires_title_and_artist_match():
    assert select.select_search_result([rec(trackName="Lucky")], "Airbag", "Radiohead", 284) is None
    assert select.select_search_result([rec(artistName="Some Cover Band")], "Airbag", "Radiohead", 284) is None
    assert select.select_search_result([rec(trackName="Airbag - Remastered")], "Airbag", "Radiohead", 284)


def test_synced_problem():
    assert select.synced_problem(rec(), AUDIO_S, 284.4) is None
    assert select.synced_problem(rec(), AUDIO_S, None) is None  # MusicBrainz length unknown
    assert select.synced_problem(rec(), None, 284.4)
    assert select.synced_problem(rec(), AUDIO_S, 284.4, composite=True)
    assert select.synced_problem(rec(duration=285.6), AUDIO_S, 284.4)  # LRCLIB vs file > 1 s
    assert select.synced_problem(rec(duration=None), AUDIO_S, 284.4)
    assert select.synced_problem(rec(), AUDIO_S, 282.0)  # MusicBrainz vs file > 1 s
    assert select.synced_problem(rec(syncedLyrics="[00:01.00]Only\n[00:02.00]two lines"), AUDIO_S, None)
    out_of_order = SYNCED.replace("[00:44.10]", "[00:10.00]")
    assert select.synced_problem(rec(syncedLyrics=out_of_order), AUDIO_S, None) == "timestamps out of order"
    too_late = SYNCED + "\n[04:50.00]After the end"
    assert select.synced_problem(rec(syncedLyrics=too_late), AUDIO_S, None).startswith("last line")


def test_line_times_handles_repeated_lines_and_blank_stamps():
    lines = select.line_times("[ar:x]\n[00:10.50][01:20.5]Chorus\n[00:30.00]\n[00:40]Verse")
    assert lines == [[10.5, 80.5], [40.0]]


def test_select_prefers_synced():
    results = [rec(id=1, syncedLyrics=None), rec(id=2)]
    assert select.select_search_result(results, "Airbag", "Radiohead", 284)["id"] == 2
    assert select.select_search_result(results, "Airbag", "Radiohead", 284, prefer_synced=False)["id"] == 1


def test_select_skips_empty_records():
    assert select.select_search_result([rec(plainLyrics=None, syncedLyrics=None)], "Airbag", "Radiohead", 284) is None


def test_classify():
    assert select.classify(None) == "not_found"
    assert select.classify(rec(instrumental=True, plainLyrics=None, syncedLyrics=None)) == "instrumental"
    assert select.classify(rec()) == "synced"
    assert select.classify(rec(), prefer_synced=False) == "plain"
    assert select.classify(rec(syncedLyrics=None)) == "plain"


# --- formatting ----------------------------------------------------------------------------

def test_format_lrc_headers():
    out = select.format_lrc(SYNCED, artist="Radiohead", album="OK Computer", title="Airbag", length_s=284.4)
    lines = out.splitlines()
    assert lines[:4] == ["[ar:Radiohead]", "[al:OK Computer]", "[ti:Airbag]", "[length:04:44]"]
    assert lines[4] == "[00:24.24]In the next world war"
    assert out.endswith("\n")


def test_format_lrc_replaces_existing_headers():
    src = "[ar:Wrong]\n[ti:Wrong]\n" + SYNCED
    out = select.format_lrc(src, artist="Radiohead", album="OK Computer", title="Airbag", length_s=60)
    assert "Wrong" not in out
    assert out.count("[ar:") == 1


def test_strip_timestamps():
    assert select.strip_timestamps("[ar:x]\n" + SYNCED) == PLAIN
    assert select.format_length(61) == "01:01"


def test_embed_text_prefers_plain():
    assert LyricsOutcome("synced", synced=SYNCED, plain=PLAIN).embed_text == PLAIN
    assert LyricsOutcome("synced", synced=SYNCED).embed_text == PLAIN
    assert LyricsOutcome("instrumental").embed_text is None
    assert LyricsOutcome("error").embed_text is None


# --- service with a mocked LRCLIB -----------------------------------------------------------

def transport(get_resp, search_resp=None, calls=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((request.url.path, dict(request.url.params), request.headers.get("user-agent")))
        if request.url.path == "/api/get":
            return get_resp if isinstance(get_resp, httpx.Response) else httpx.Response(200, json=get_resp)
        if request.url.path == "/api/search":
            return httpx.Response(200, json=search_resp or [])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_get_hit_sends_expected_params():
    calls = []
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S, transport=transport(rec(), calls=calls))
    assert out.status == "synced"
    path, params, ua = calls[0]
    assert path == "/api/get"
    assert params == {"artist_name": "Radiohead", "track_name": "Airbag", "album_name": "OK Computer", "duration": "284"}
    assert ua.startswith("Ofy/")



async def test_get_leaves_out_a_duration_over_an_hour():
    calls = []
    await fetch_for_model(model(), Settings(), audio_s=3612.0, transport=transport(rec(), calls=calls))
    path, params, _ = calls[0]
    assert path == "/api/get" and "duration" not in params

async def test_404_falls_back_to_search():
    calls = []
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S,
                                transport=transport(httpx.Response(404), [rec(duration=300.0), rec(syncedLyrics=None)], calls))
    assert [c[0] for c in calls] == ["/api/get", "/api/search"]
    assert out.status == "plain"


async def test_search_with_no_acceptable_result_is_not_found():
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S,
                                transport=transport(httpx.Response(404), [rec(duration=200.0)]))
    assert out.status == "not_found"


async def test_blank_lyrics_are_no_lyrics():
    blank = rec(duration=284.0, plainLyrics=" \r\n", syncedLyrics="[00:00.00]\r\n")
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S, transport=transport(
        blank, [blank, rec(duration=284.0, instrumental=True, plainLyrics=None, syncedLyrics=None)]))
    assert out.status == "instrumental"
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S, transport=transport(blank, [blank]))
    assert out.status == "not_found"


async def test_instrumental():
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S,
                                transport=transport(rec(instrumental=True, plainLyrics=None, syncedLyrics=None)))
    assert out.status == "instrumental"


async def test_synced_timed_for_another_length_falls_back_to_a_matching_entry():
    calls = []
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S, transport=transport(
        rec(id=1, duration=286.0), [rec(id=2, duration=286.0), rec(id=3, duration=284.0)], calls))
    assert [c[0] for c in calls] == ["/api/get", "/api/search"]
    assert out.status == "synced"


async def test_untrusted_synced_becomes_plain():
    # Only an entry timed 1.6 s off the file: keep the words, drop the timing
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S,
                                transport=transport(rec(duration=286.0), [rec(duration=286.0)]))
    assert out.status == "plain" and out.embed_text == PLAIN


async def test_synced_needs_the_real_file_length():
    out = await fetch_for_model(model(), Settings(), audio_s=None, transport=transport(rec()))
    assert out.status == "plain"


async def test_synced_not_trusted_for_joined_videos():
    out = await fetch_for_model(model(youtube_video_id="abc+def"), Settings(), audio_s=AUDIO_S,
                                transport=transport(rec(), [rec()]))
    assert out.status == "plain"


async def test_network_failure_is_reported_not_raised():
    out = await fetch_for_model(model(), Settings(lrclib_url="http://lrclib.invalid"), audio_s=AUDIO_S)
    assert out.status == "error"


def test_retry_after():
    assert lyrics_client._retry_after(httpx.Response(429, headers={"Retry-After": "1"})) == 1.0
    assert lyrics_client._retry_after(httpx.Response(429)) == 5.0


async def test_too_many_requests_waits_and_retries(monkeypatch):
    monkeypatch.setattr(lyrics_client, "_retry_after", lambda r: 0.0)
    answers = [httpx.Response(429, headers={"Retry-After": "1"}), httpx.Response(503), httpx.Response(200, json=rec())]
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S,
                                transport=httpx.MockTransport(lambda request: answers.pop(0)))
    assert out.status == "synced" and answers == []


async def test_server_error_is_reported(monkeypatch):
    monkeypatch.setattr(lyrics_client, "_retry_after", lambda r: 0.0)
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S, transport=transport(httpx.Response(500)))
    assert out.status == "error"
    out = await fetch_for_model(model(), Settings(), audio_s=AUDIO_S, transport=transport(httpx.Response(503)))
    assert out.status == "error"


# --- sidecars --------------------------------------------------------------------------------

@pytest.fixture
def audio(tmp_path):
    p = tmp_path / "1-01 - Airbag.mp3"
    p.write_bytes(b"x")
    return p


def test_sidecar_synced(audio):
    status, path = write_sidecar(audio, LyricsOutcome("synced", synced=SYNCED, plain=PLAIN), model(), Settings())
    assert status == "synced" and path == audio.with_suffix(".lrc")
    assert path.read_text().startswith("[ar:Radiohead]\n[al:OK Computer]\n[ti:Airbag]\n[length:04:44]\n")


def test_sidecar_plain_writes_no_file_and_removes_old_ones(audio):
    audio.with_suffix(".lrc").write_text("old")
    audio.with_suffix(".txt").write_text("from an older version")
    status, path = write_sidecar(audio, LyricsOutcome("plain", plain=PLAIN), model(), Settings())
    assert status == "plain" and path is None  # plain lyrics live in the tags only
    assert not audio.with_suffix(".lrc").exists() and not audio.with_suffix(".txt").exists()


def test_sidecar_plain_without_embedding_saves_nothing(audio):
    status, path = write_sidecar(audio, LyricsOutcome("plain", plain=PLAIN), model(), Settings(lyrics_embed=False))
    assert status == "none" and path is None


def test_sidecar_synced_removes_old_txt(audio):
    audio.with_suffix(".txt").write_text("from an older version")
    write_sidecar(audio, LyricsOutcome("synced", synced=SYNCED, plain=PLAIN), model(), Settings())
    assert not audio.with_suffix(".txt").exists()


def test_sidecar_instrumental_removes_files(audio):
    audio.with_suffix(".txt").write_text("old")
    status, path = write_sidecar(audio, LyricsOutcome("instrumental"), model(), Settings())
    assert status == "instrumental" and path is None
    assert not audio.with_suffix(".txt").exists()


def test_sidecar_error_keeps_existing(audio):
    audio.with_suffix(".lrc").write_text("keep")
    status, path = write_sidecar(audio, LyricsOutcome("error"), model(), Settings())
    assert status == "synced" and path.read_text() == "keep"
    status, path = write_sidecar(audio.with_name("other.mp3"), LyricsOutcome("error"), model(), Settings())
    assert status == "none" and path is None
