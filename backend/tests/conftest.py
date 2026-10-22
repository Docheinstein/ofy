import json
from pathlib import Path

import pytest
from sqlmodel import create_engine

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def fixture():
    return load_fixture


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    from ofy import db

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    db.set_engine(engine)
    yield engine
    db._engine = None


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Async clients/limiters bind to an event loop; give every test fresh ones."""
    from ofy import listenbrainz
    from ofy.match import ytm
    from ofy.mb import client

    client._client = None
    ytm._service = None
    listenbrainz._client = None
    listenbrainz._down_until = 0.0
    yield
    client._client = None
    ytm._service = None
    listenbrainz._client = None
    listenbrainz._down_until = 0.0
