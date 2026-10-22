"""Play counts from ListenBrainz (its popularity API, keyed on MusicBrainz ids), when enabled in the settings.

Light on the network: a page asks once for all the ids it shows (up to 1000 per request), every count
is cached for a week (unknown ones too), and after a failure ListenBrainz is left alone for a while.
When it's slow or down, pages just show no counts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterable
from typing import Any, Literal

import httpx
from sqlmodel import col, select

from ofy.config import env
from ofy.db import CacheEntry, load_settings, session
from ofy.ratelimit import RateLimiter

log = logging.getLogger(__name__)

API = "https://api.listenbrainz.org/1/popularity"
TTL = 7 * 86400.0
BATCH = 1000  # the most ids ListenBrainz takes in one request
BACKOFF = 300.0  # seconds without asking after a failure

Kind = Literal["release-group", "recording"]
_FIELD = {"release-group": "release_group_mbid", "recording": "recording_mbid"}

# ListenBrainz allows 30 requests every 10 seconds; one page needs one or two.
_limiter = RateLimiter(0.5)
_client: httpx.AsyncClient | None = None
_down_until = 0.0


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(headers={"User-Agent": env.user_agent}, timeout=8)
    return _client


def enabled() -> bool:
    return load_settings().listenbrainz


def parse_counts(kind: Kind, data: Any) -> dict[str, int | None]:
    """id -> total listen count (None when ListenBrainz has none) from a popularity response."""
    field = _FIELD[kind]
    out: dict[str, int | None] = {}
    for row in data if isinstance(data, list) else []:
        mbid = row.get(field)
        if mbid:
            n = row.get("total_listen_count")
            out[mbid] = int(n) if isinstance(n, int | float) else None
    return out


def _key(kind: Kind, mbid: str) -> str:
    return f"lb:{kind}:{mbid}"


def _cached(kind: Kind, ids: list[str]) -> dict[str, int | None]:
    out: dict[str, int | None] = {}
    now = time.time()
    with session() as s:
        for i in range(0, len(ids), 500):  # stay under SQLite's limit on query parameters
            keys = [_key(kind, m) for m in ids[i:i + 500]]
            for row in s.exec(select(CacheEntry).where(col(CacheEntry.key).in_(keys))).all():
                if row.expires_at >= now:
                    out[row.key.rsplit(":", 1)[1]] = json.loads(row.value)
    return out


def _store(kind: Kind, counts: dict[str, int | None]) -> None:
    expires = time.time() + TTL
    with session() as s:
        for mbid, n in counts.items():
            row = s.get(CacheEntry, _key(kind, mbid)) or CacheEntry(key=_key(kind, mbid), value="", expires_at=0)
            row.value = json.dumps(n)
            row.expires_at = expires
            s.add(row)
        s.commit()


async def _fetch(kind: Kind, ids: list[str]) -> dict[str, int | None] | None:
    """One popularity request; None when ListenBrainz couldn't answer."""
    global _down_until
    if time.time() < _down_until:
        return None
    url = f"{API}/{kind}"
    for _attempt in range(2):
        async with _limiter:
            try:
                resp = await _http().post(url, json={f"{_FIELD[kind]}s": ids})
            except httpx.HTTPError as e:
                log.info("ListenBrainz unavailable: %s", e)
                break
        if resp.status_code == 200:
            counts = parse_counts(kind, resp.json())
            # ids it doesn't know come back without a count; remember them as such
            return {m: counts.get(m) for m in ids}
        if resp.status_code != 429:
            log.info("ListenBrainz answered %s: %s", resp.status_code, resp.text[:200])
            break
        try:
            wait = float(resp.headers.get("x-ratelimit-reset-in", "2"))
        except ValueError:
            wait = 2.0
        await asyncio.sleep(min(10.0, max(0.5, wait)))
    _down_until = time.time() + BACKOFF
    return None


async def plays(kind: Kind, ids: Iterable[str | None]) -> dict[str, int | None]:
    """Play counts for these MusicBrainz ids; empty when disabled, ids not known are left out."""
    wanted = list(dict.fromkeys(i for i in ids if i and not i.startswith("local-")))
    if not wanted or not enabled():
        return {}
    out = await asyncio.to_thread(_cached, kind, wanted)
    missing = [i for i in wanted if i not in out]
    for i in range(0, len(missing), BATCH):
        fetched = await _fetch(kind, missing[i:i + BATCH])
        if fetched is None:
            break
        await asyncio.to_thread(_store, kind, fetched)
        out.update(fetched)
    return out


async def attach(kind: Kind, items: list[dict[str, Any]], id_key: str = "id") -> None:
    """Set ``plays`` on each item (by its ``id_key``); items stay untouched when it's disabled."""
    if not items or not enabled():
        return
    counts = await plays(kind, (it.get(id_key) for it in items))
    for it in items:
        it["plays"] = counts.get(it.get(id_key) or "")
