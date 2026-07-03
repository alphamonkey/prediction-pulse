"""Dashboard `/api/trends` — live Bluesky trends with a server-side TTL cache.

The dashboard fetches trends live (small, ephemeral data — no history tracking), reusing the
`BlueskyTrendClient` shape. A `FakeTrendClient` stands in for the network at the boundary.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pulse import config
from pulse.server.app import create_app
from pulse.venue.trending import Trend


class FakeTrendClient:
    def __init__(self, trends, *, fail=False):
        self._trends = trends
        self._fail = fail
        self.calls = 0

    def get_trends(self, *, limit):
        self.calls += 1
        if self._fail:
            return []  # BlueskyTrendClient degrades failures to [] itself
        return self._trends[:limit]


@pytest.fixture
def boot_db(tmp_path, monkeypatch):
    # create_app boots a DB (schema); point it at a temp path.
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "dash.db"))


def _client(boot_db, trend_client):
    return TestClient(create_app(trend_client=trend_client))


def test_trends_endpoint_generic_shape(boot_db):
    tc = FakeTrendClient([
        Trend("World Cup", 3200, "Sports"),
        Trend("Fed decision", 800, "News"),
    ])
    rows = _client(boot_db, tc).get("/api/trends").json()
    assert rows == [
        {"name": "World Cup", "post_count": 3200, "category": "Sports", "platform": "bluesky"},
        {"name": "Fed decision", "post_count": 800, "category": "News", "platform": "bluesky"},
    ]


def test_trends_endpoint_respects_limit(boot_db):
    tc = FakeTrendClient([Trend(f"T{i}", 100 - i, None) for i in range(20)])
    rows = _client(boot_db, tc).get("/api/trends?limit=3").json()
    assert [r["name"] for r in rows] == ["T0", "T1", "T2"]


def test_trends_are_cached_within_ttl(boot_db):
    tc = FakeTrendClient([Trend("World Cup", 3200, "Sports")])
    client = _client(boot_db, tc)
    client.get("/api/trends")
    client.get("/api/trends")
    assert tc.calls == 1  # second request served from cache


def test_trends_failure_returns_empty(boot_db):
    tc = FakeTrendClient([], fail=True)
    rows = _client(boot_db, tc).get("/api/trends").json()
    assert rows == []
