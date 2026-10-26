"""LRCLIB HTTP client (https://lrclib.net/docs), politely throttled."""

from __future__ import annotations

from typing import Any

import httpx

from ofy.config import env
from ofy.ratelimit import RateLimiter

_limiter = RateLimiter(0.5)
RATE_LIMIT_RETRIES = 6
BUSY = (429, 502, 503, 504)  # too many requests, or the server overloaded: worth waiting for


class LrclibError(RuntimeError):
    pass


def _retry_after(r: httpx.Response) -> float:
    try:
        return max(1.0, min(60.0, float(r.headers.get("retry-after", ""))))
    except ValueError:
        return 5.0


class LrclibClient:
    def __init__(self, base_url: str, *, transport: httpx.AsyncBaseTransport | None = None, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            headers={"User-Agent": env.user_agent}, timeout=timeout, transport=transport, follow_redirects=True
        )

    async def __aenter__(self) -> LrclibClient:
        return self

    async def __aexit__(self, *exc) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any]) -> httpx.Response:
        """The response; a 429 (too many requests) or an overloaded server holds back every lookup for its
        Retry-After (5 s without one), longer each time, then retries."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            async with _limiter:
                try:
                    r = await self._client.get(f"{self.base_url}{path}", params=params)
                except httpx.HTTPError as e:
                    raise LrclibError(f"LRCLIB request failed: {e}") from e
            if r.status_code not in BUSY or attempt == RATE_LIMIT_RETRIES:
                return r
            _limiter.pause(_retry_after(r) * (attempt + 1))
        return r

    async def get(self, *, artist: str, title: str, album: str, duration: int | None) -> dict[str, Any] | None:
        params: dict[str, Any] = {"artist_name": artist, "track_name": title, "album_name": album}
        if duration is not None:
            params["duration"] = duration
        r = await self._get("/api/get", params)
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise LrclibError(f"LRCLIB /api/get returned {r.status_code}")
        return r.json()

    async def search(self, *, artist: str, title: str, album: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"track_name": title, "artist_name": artist}
        if album:
            params["album_name"] = album
        r = await self._get("/api/search", params)
        if r.status_code != 200:
            raise LrclibError(f"LRCLIB /api/search returned {r.status_code}")
        data = r.json()
        if not data and album:
            # Retry without album: compilations/reissues often differ in album name.
            r = await self._get("/api/search", {"track_name": title, "artist_name": artist})
            data = r.json() if r.status_code == 200 else []
        return data if isinstance(data, list) else []
