from ofy.library.scanner import DbTrack, FoundFile, lyrics_from_sidecars, plan_reconcile
from ofy.library.status import album_status, album_summary


def test_album_status_aggregation():
    assert album_status([], 12) == "none"
    assert album_status(["none"] * 12, 12) == "none"
    assert album_status(["queued", "downloading"], 12) == "none"
    assert album_status(["done"] * 11 + ["failed"], 12) == "partial"
    assert album_status(["done"] * 3, 12) == "partial"  # tracks without rows count as missing
    assert album_status(["done"] * 12, 12) == "complete"
    assert album_status(["done"] * 2) == "complete"


def test_album_summary_counts():
    s = album_summary(["done", "done", "queued", "downloading", "failed", "needs_review"], 8)
    assert s == {"status": "partial", "total": 8, "done": 2, "active": 2, "failed": 1, "needs_review": 1}


def test_lyrics_from_sidecars():
    assert lyrics_from_sidecars("none", "synced") == "synced"
    assert lyrics_from_sidecars("synced", "none") == "none"
    assert lyrics_from_sidecars("instrumental", "none") == "instrumental"
    assert lyrics_from_sidecars("not_found", "synced") == "synced"
    assert lyrics_from_sidecars("plain", "none") == "plain"  # embedded in the tags, no sidecar


def test_deleted_audio_resets_track():
    db = [DbTrack("a", "done", "/m/a.mp3", "synced", "mp3", "/m/a.lrc")]
    (c,) = plan_reconcile(db, {})
    assert c.fields["status"] == "none" and c.fields["file_path"] is None and c.fields["lyrics_status"] == "none"


def test_unchanged_produces_no_changes():
    db = [DbTrack("a", "done", "/m/a.mp3", "synced", "mp3", "/m/a.lrc")]
    assert plan_reconcile(db, {"a": FoundFile("/m/a.mp3", "mp3", "synced")}) == []


def test_deleted_lrc_updates_lyrics():
    db = [DbTrack("a", "done", "/m/a.mp3", "synced", "mp3", "/m/a.lrc")]
    (c,) = plan_reconcile(db, {"a": FoundFile("/m/a.mp3", "mp3", "none")})
    assert c.fields == {"lyrics_status": "none", "lyrics_path": None}


def test_added_lrc_detected():
    db = [DbTrack("a", "done", "/m/a.mp3", "plain", "mp3", None)]
    (c,) = plan_reconcile(db, {"a": FoundFile("/m/a.mp3", "mp3", "synced")})
    assert c.fields == {"lyrics_status": "synced", "lyrics_path": "/m/a.lrc"}


def test_legacy_txt_path_dropped_plain_kept():
    db = [DbTrack("a", "done", "/m/a.mp3", "plain", "mp3", "/m/a.txt")]
    (c,) = plan_reconcile(db, {"a": FoundFile("/m/a.mp3", "mp3", "none")})
    assert c.fields == {"lyrics_path": None}


def test_moved_file_followed():
    db = [DbTrack("a", "done", "/m/old.mp3", "none", "mp3", None)]
    (c,) = plan_reconcile(db, {"a": FoundFile("/m/new.mp3", "mp3", "none", tags={})})
    assert c.fields == {"file_path": "/m/new.mp3"}


def test_reappeared_file_marks_done():
    db = [DbTrack("a", "none", None, "none")]
    (c,) = plan_reconcile(db, {"a": FoundFile("/m/a.opus", "opus", "synced", tags={"x": ["y"]})})
    assert c.fields["status"] == "done" and c.fields["file_format"] == "opus" and c.fields["lyrics_status"] == "synced"


def test_unknown_file_creates_row():
    tags = {"musicbrainz_trackid": ["z"], "musicbrainz_albumid": ["rel"], "title": ["T"]}
    (c,) = plan_reconcile([], {"z": FoundFile("/m/z.mp3", "mp3", "none", tags=tags)})
    assert c.new_row == tags and c.fields["status"] == "done"


def test_active_tracks_untouched():
    db = [DbTrack("a", "downloading", None, "none")]
    assert plan_reconcile(db, {"a": FoundFile("/m/a.mp3", "mp3", "none", tags={})}) == []
