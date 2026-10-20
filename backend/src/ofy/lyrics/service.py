"""Lyrics step: fetch from LRCLIB, decide what to save, write the .lrc sidecar. Best-effort.

Synced lyrics go to "<basename>.lrc"; plain lyrics are only embedded in the tags (no .txt sidecar).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import httpx

from ofy.config import Settings
from ofy.lyrics import select
from ofy.lyrics.client import LrclibClient, LrclibError
from ofy.tagging import writers
from ofy.tagging.model import TagModel

log = logging.getLogger(__name__)


@dataclass
class LyricsOutcome:
    status: str  # synced | plain | instrumental | not_found | error
    synced: str | None = None
    plain: str | None = None
    error: str | None = None

    @property
    def embed_text(self) -> str | None:
        """Plain (unsynchronized) lyrics for embedding in tags."""
        if self.status in ("synced", "plain"):
            if self.plain:
                return self.plain.strip()
            if self.synced:
                return select.strip_timestamps(self.synced)
        return None


def _has_lyrics(r: dict | None) -> bool:
    return bool(r and (r.get("syncedLyrics") or r.get("plainLyrics") or r.get("instrumental")))


def outcome_from_record(r: dict | None, prefer_synced: bool) -> LyricsOutcome:
    status = select.classify(r, prefer_synced)
    if status in ("not_found", "instrumental") or r is None:
        return LyricsOutcome(status)
    return LyricsOutcome(status, synced=r.get("syncedLyrics") or None, plain=r.get("plainLyrics") or None)


async def fetch_for_model(model: TagModel, settings: Settings, *, audio_s: float | None,
                          transport: httpx.AsyncBaseTransport | None = None) -> LyricsOutcome:
    """Lyrics for the file whose real length is ``audio_s``. Synced lyrics that can't be trusted to be
    timed to this file come back as plain. Never raises: failures are reported as status 'error'."""
    mb_s = model.length_ms / 1000 if model.length_ms else None
    reference = audio_s if audio_s is not None else mb_s
    duration = round(reference) if reference else None
    artist = model.artist or model.albumartist
    prefer = settings.lyrics_prefer_synced
    composite = "+" in (model.youtube_video_id or "")

    def problem(r: dict) -> str | None:
        return select.synced_problem(r, audio_s, mb_s, composite=composite)

    try:
        async with LrclibClient(settings.lrclib_url, transport=transport) as c:
            rec = await c.get(artist=artist, title=model.title, album=model.album, duration=duration)
            if not _has_lyrics(rec) or (prefer and rec.get("syncedLyrics") and problem(rec)):
                # Nothing usable, or synced lyrics timed for another cut: another LRCLIB entry may fit.
                results = await c.search(artist=artist, title=model.title, album=model.album)
                trusted = [r for r in results if r.get("syncedLyrics") and not problem(r)] if prefer else []
                rec = (select.select_search_result(trusted, model.title, artist, duration)
                       or (rec if _has_lyrics(rec) else None)
                       or select.select_search_result(results, model.title, artist, duration, prefer_synced=prefer))
        out = outcome_from_record(rec, prefer)
        if out.status == "synced" and rec is not None:
            if reason := problem(rec):
                log.info("synced lyrics for %s – %s not trusted (%s); keeping them as plain", artist, model.title, reason)
                out = LyricsOutcome("plain", synced=out.synced, plain=out.plain)
        return out
    except (LrclibError, httpx.HTTPError, ValueError) as e:
        log.warning("lyrics lookup failed for %s – %s: %s", artist, model.title, e)
        return LyricsOutcome("error", error=str(e))
    except Exception as e:  # pragma: no cover - lyrics must never break a download
        log.exception("unexpected lyrics failure")
        return LyricsOutcome("error", error=str(e))


def saved_status(audio: Path) -> str:
    """synced (.lrc next to the file) | plain (lyrics embedded in the tags) | none."""
    if audio.with_suffix(".lrc").is_file():
        return "synced"
    try:
        return "plain" if writers.get_lyrics(audio) else "none"
    except Exception:
        return "none"


def _write_text(path: Path, text: str) -> None:
    tmp = path.with_name(f".{path.name}.part")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_sidecar(audio: Path, outcome: LyricsOutcome, model: TagModel, settings: Settings) -> tuple[str, Path | None]:
    """Write "<basename>.lrc" next to the audio file for synced lyrics. Returns (status, path).

    Plain lyrics get no sidecar (they're embedded in the tags by the caller), so they are status "plain"
    only with embedding on. .txt sidecars written by older versions are removed whenever lyrics are saved.
    """
    lrc, txt = audio.with_suffix(".lrc"), audio.with_suffix(".txt")
    try:
        if outcome.status == "error":
            st = saved_status(audio)
            return st, (lrc if st == "synced" else None)
        if outcome.status == "synced" and outcome.synced:
            length = writers.audio_length(audio) or (model.length_ms / 1000 if model.length_ms else None)
            _write_text(lrc, select.format_lrc(outcome.synced, artist=model.artist, album=model.album,
                                               title=model.title, length_s=length))
            txt.unlink(missing_ok=True)
            return "synced", lrc
        if outcome.status in ("plain", "synced"):
            lrc.unlink(missing_ok=True)
            txt.unlink(missing_ok=True)
            return ("plain" if settings.lyrics_embed and outcome.embed_text else "none"), None
        if outcome.status == "instrumental":
            lrc.unlink(missing_ok=True)
            txt.unlink(missing_ok=True)
            return "instrumental", None
        return "not_found", None
    except OSError as e:
        log.warning("writing lyrics sidecar failed: %s", e)
        return saved_status(audio), None
