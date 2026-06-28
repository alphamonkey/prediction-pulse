"""Tests for the KPM dashboard endpoints (/api/kpms, /api/followers, /api/top-posts)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pulse import config
from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.publish.base import PostResult
from pulse.store.db import Database

_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "dash.db"
    db = Database(path)
    db.connect()
    db.insert_account_snapshot(AccountStats(100, 50, 10, _NOW - timedelta(days=2)))
    db.insert_account_snapshot(AccountStats(120, 60, 15, _NOW))
    db.insert_post("k1", "gnome",
                   PostResult(channel="bluesky", posted=True, uri="at://1", cid="c", text="alpha"))
    db.upsert_post_metrics([PostEngagement("at://1", "bluesky", _NOW,
                                           {MetricKind.LIKES: 10, MetricKind.REPLIES: 2})])
    db.close()

    monkeypatch.setattr(config, "DB_PATH", str(path))
    from pulse.server.app import create_app
    return TestClient(create_app())


def test_kpms_endpoint(client):
    k = client.get("/api/kpms").json()
    assert k["followers"] == 120
    assert k["follower_delta_7d"] == 20
    assert k["applause"] == 10.0
    assert k["conversation"] == 2.0
    assert k["total_engagements"] == 12


def test_followers_endpoint(client):
    rows = client.get("/api/followers").json()
    assert [r["followers"] for r in rows] == [100, 120]


def test_top_posts_endpoint(client):
    rows = client.get("/api/top-posts?limit=5").json()
    assert rows[0]["uri"] == "at://1"
    assert rows[0]["text"] == "alpha"
    assert rows[0]["total"] == 12
