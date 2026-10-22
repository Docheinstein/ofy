import asyncio
import json

import httpx
import pytest

from ofy import listenbrainz
from ofy.config import Settings
from ofy.db import save_settings
from ofy.listenbrainz import attach, parse_counts, plays


@pytest.fixture
def lb(tmp_db):
    """A fake ListenBrainz: knows 'a' (10 plays) and 'b' (no listens); records every request body."""
    requests: list[dict] = []
    status = {"code": 200}

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        requests.append(body)
        if status["code"] != 200:
            return httpx.Response(status["code"])
        ids = body.get("recording_mbids") or body.get("release_group_mbids")
        field = "recording_mbid" if "recording_mbids" in body else "release_group_mbid"
        known = {"a": 10, "b": None}
        return httpx.Response(200, json=[{field: i, "total_listen_count": known[i]} for i in ids if i in known])

    listenbrainz._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    listenbrainz._limiter.interval = 0
    yield requests, status
    listenbrainz._limiter.interval = 0.5


def test_parse_counts():
    data = [{"recording_mbid": "x", "total_listen_count": 5}, {"recording_mbid": "y", "total_listen_count": None}]
    assert parse_counts("recording", data) == {"x": 5, "y": None}
    assert parse_counts("recording", {"error": "nope"}) == {}


def test_one_request_per_page_then_cached(lb):
    requests, _ = lb
    counts = asyncio.run(plays("recording", ["a", "b", "c", "a", None, "local-xyz"]))
    assert counts == {"a": 10, "b": None, "c": None}
    assert requests == [{"recording_mbids": ["a", "b", "c"]}]
    assert asyncio.run(plays("recording", ["a", "c"])) == {"a": 10, "c": None}
    assert len(requests) == 1  # unknown ids are remembered too


def test_large_pages_are_batched(lb):
    requests, _ = lb
    asyncio.run(plays("release-group", [f"id{i}" for i in range(1500)]))
    assert [len(r["release_group_mbids"]) for r in requests] == [1000, 500]


def test_attach_and_disabled(lb):
    requests, _ = lb
    items = [{"id": "a"}, {"id": "zzz"}]
    asyncio.run(attach("release-group", items))
    assert items == [{"id": "a", "plays": 10}, {"id": "zzz", "plays": None}]
    save_settings(Settings(listenbrainz=False))
    items = [{"id": "b"}]
    asyncio.run(attach("release-group", items))
    assert items == [{"id": "b"}] and len(requests) == 1


def test_failure_backs_off(lb):
    requests, status = lb
    status["code"] = 503
    assert asyncio.run(plays("recording", ["a"])) == {}
    assert asyncio.run(plays("recording", ["b"])) == {}
    assert len(requests) == 1  # left alone for a while after failing
