"""Tests for the read-only dashboard API (FastAPI TestClient + seeded temp DB)."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from pulse import config
from pulse.models import Event, Snapshot, ValueKind
from pulse.store.db import Database
from pulse.writer.base import Draft

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _ev(dedup_key, rule="odds_swing"):
    return Event(
        rule=rule, venue="kalshi", market_id="KXTEST", ts=_T,
        value_kind=ValueKind.PROBABILITY, from_value=0.40, to_value=0.55,
        magnitude=0.15, direction="up", headline="KXTEST: odds 40% -> 55%",
        dedup_key=dedup_key,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    path = tmp_path / "dash.db"
    db = Database(path)
    db.connect()
    db.insert_snapshot(Snapshot("kalshi", "A", _T, 0.5, ValueKind.PROBABILITY))
    db.insert_snapshot(Snapshot("kalshi", "B", _T + timedelta(minutes=10), 0.6,
                                ValueKind.PROBABILITY))
    db.record_posted(_ev("k1", rule="milestone"))
    db.record_posted(_ev("k2", rule="odds_swing"))
    db.insert_draft(Draft(event_dedup_key="k1", persona="example", text="A punchy post."))
    db.close()

    monkeypatch.setattr(config, "DB_PATH", str(path))
    from pulse.server.app import create_app
    return TestClient(create_app())


def test_stats_endpoint(client):
    r = client.get("/api/stats").json()
    assert r["mode"] == config.PULSE_MODE
    assert r["snapshots"] == 2
    assert r["markets_tracked"] == 2
    assert r["events_total"] == 2
    assert r["events_by_rule"] == {"milestone": 1, "odds_swing": 1}
    assert r["drafts"] == 1


def test_events_endpoint_caps_and_orders(client):
    rows = client.get("/api/events?limit=1").json()
    assert len(rows) == 1
    assert {"rule", "market_id", "headline", "created_at"} <= set(rows[0].keys())


def test_drafts_endpoint(client):
    rows = client.get("/api/drafts").json()
    assert len(rows) == 1
    assert rows[0]["text"] == "A punchy post."
    assert rows[0]["persona"] == "example"


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
