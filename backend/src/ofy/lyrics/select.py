"""LRCLIB result selection and .lrc formatting (pure)."""

from __future__ import annotations

import re
from typing import Any

from ofy.match.scoring import artist_similarity, text_similarity

DURATION_TOLERANCE = 2.0
MATCH_THRESHOLD = 0.8
# Synced lyrics are only trusted when the downloaded file is this close to the length they were timed
# against (and to MusicBrainz's length); otherwise they're saved as plain lyrics.
SYNCED_TOLERANCE = 1.0
MIN_SYNCED_LINES = 5

_TIMESTAMP = re.compile(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]")
_TIMESTAMP_PARTS = re.compile(r"\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]")
_HEADER = re.compile(r"^\[(ar|al|ti|au|length|by|offset|re|ve|#):.*\]\s*$", re.I)


def result_score(r: dict[str, Any], title: str, artist: str) -> float:
    t = text_similarity(title, r.get("trackName") or r.get("name"))
    a = artist_similarity(artist, [r.get("artistName") or ""])
    return 0.6 * t + 0.4 * a


def select_search_result(results: list[dict[str, Any]], title: str, artist: str, duration_s: float | None, *,
                         tolerance: float = DURATION_TOLERANCE, threshold: float = MATCH_THRESHOLD,
                         prefer_synced: bool = True) -> dict[str, Any] | None:
    """Best /api/search result within ±tolerance seconds whose title/artist match above threshold."""
    ok: list[tuple[float, dict[str, Any]]] = []
    for r in results:
        if duration_s is not None:
            d = r.get("duration")
            if d is None or abs(float(d) - duration_s) > tolerance:
                continue
        t = text_similarity(title, r.get("trackName") or r.get("name"))
        a = artist_similarity(artist, [r.get("artistName") or ""])
        if t < threshold or a < threshold:
            continue
        score = 0.6 * t + 0.4 * a
        has_lyrics = bool(r.get("syncedLyrics") or r.get("plainLyrics") or r.get("instrumental"))
        if not has_lyrics:
            continue
        if prefer_synced and r.get("syncedLyrics"):
            score += 0.05
        ok.append((score, r))
    if not ok:
        return None
    ok.sort(key=lambda p: -p[0])
    return ok[0][1]


def line_times(synced: str) -> list[list[float]]:
    """Timestamps in seconds of every line that has text, in file order (a repeated line has several)."""
    lines = []
    for line in synced.splitlines():
        stamps = list(_TIMESTAMP_PARTS.finditer(line))
        if not stamps or not _TIMESTAMP.sub("", line).strip():
            continue
        lines.append([int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3) or 0) / 10 ** len(m.group(3) or "0")
                      for m in stamps])
    return lines


def synced_problem(r: dict[str, Any], audio_s: float | None, mb_s: float | None, *,
                   composite: bool = False, tolerance: float = SYNCED_TOLERANCE) -> str | None:
    """Why the record's synced lyrics can't be trusted to be timed to this file, or None if they can."""
    if audio_s is None:
        return "length of the audio file unknown"
    if composite:
        return "audio joined from several videos"
    d = r.get("duration")
    if d is None or abs(float(d) - audio_s) > tolerance:
        return f"lyrics timed for {d}s, file is {audio_s:.1f}s"
    if mb_s is not None and abs(mb_s - audio_s) > tolerance:
        return f"MusicBrainz length {mb_s:.1f}s, file is {audio_s:.1f}s"
    lines = line_times(r.get("syncedLyrics") or "")
    if len(lines) < MIN_SYNCED_LINES:
        return f"only {len(lines)} timed lines"
    starts = [t[0] for t in lines]
    if any(b < a for a, b in zip(starts, starts[1:])):
        return "timestamps out of order"
    last = max(max(t) for t in lines)
    if last >= audio_s:
        return f"last line at {last:.1f}s, file is {audio_s:.1f}s"
    return None


def strip_timestamps(synced: str) -> str:
    lines = []
    for line in synced.splitlines():
        if _HEADER.match(line.strip()):
            continue
        lines.append(_TIMESTAMP.sub("", line).strip())
    text = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def format_length(seconds: float | None) -> str:
    if seconds is None:
        return "00:00"
    s = int(round(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def format_lrc(synced: str, *, artist: str, album: str, title: str, length_s: float | None) -> str:
    """LRC file with [ar:], [al:], [ti:], [length:] headers; existing headers in ``synced`` are replaced."""
    body = [line.rstrip() for line in synced.strip().splitlines() if not _HEADER.match(line.strip())]
    header = [
        f"[ar:{artist}]",
        f"[al:{album}]",
        f"[ti:{title}]",
        f"[length:{format_length(length_s)}]",
    ]
    return "\n".join(header + body) + "\n"


def classify(r: dict[str, Any] | None, prefer_synced: bool = True) -> str:
    """synced | plain | instrumental | not_found for an LRCLIB record."""
    if not r:
        return "not_found"
    if r.get("instrumental"):
        return "instrumental"
    if r.get("syncedLyrics") and prefer_synced:
        return "synced"
    if r.get("plainLyrics") or r.get("syncedLyrics"):
        return "plain"
    return "not_found"
