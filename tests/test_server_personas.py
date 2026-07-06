"""Dashboard persona routing: discover data/*.db, select per request via ?persona=."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from pulse.store.db import Database


def _seed(path, *, drafts: int) -> None:
    db = Database(str(path))
    db.connect()
    from pulse.writer.base import Draft
    for i in range(drafts):
        db.insert_draft(Draft(event_dedup_key=f"k{i}", persona="p", text=f"post {i}"))
    db.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    _seed(data / "alpha.db", drafts=1)
    _seed(data / "beta.db", drafts=2)
    monkeypatch.setenv("PULSE_DATA_DIR", str(data))
    monkeypatch.delenv("PULSE_DB_PATH", raising=False)
    from pulse.server.app import create_app
    return TestClient(create_app())


def test_personas_endpoint_discovers_dbs(client):
    r = client.get("/api/personas").json()
    assert r["personas"] == ["alpha", "beta"]
    assert r["default"] == "alpha"


def test_routes_select_the_personas_db(client):
    assert client.get("/api/stats?persona=alpha").json()["drafts"] == 1
    assert client.get("/api/stats?persona=beta").json()["drafts"] == 2


def test_default_is_first_persona(client):
    assert client.get("/api/stats").json()["drafts"] == 1


def test_stats_reports_which_persona(client):
    assert client.get("/api/stats?persona=beta").json()["persona"] == "beta"


def test_unknown_persona_is_404_not_a_path(client):
    assert client.get("/api/stats?persona=nope").status_code == 404
    # path traversal shapes must not resolve to files
    assert client.get("/api/stats?persona=../alpha").status_code == 404


def test_all_data_routes_accept_persona(client):
    for route in ("/api/events", "/api/drafts", "/api/kpms",
                  "/api/followers", "/api/top-posts"):
        assert client.get(f"{route}?persona=beta").status_code == 200, route
        assert client.get(f"{route}?persona=nope").status_code == 404, route


def test_no_personas_falls_back_to_legacy_db(tmp_path, monkeypatch):
    # Pre-migration layout: no data/*.db — the dashboard serves the single legacy DB.
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path / "empty"))
    monkeypatch.setenv("PULSE_DB_PATH", str(tmp_path / "legacy.db"))
    from pulse.server.app import create_app
    client = TestClient(create_app())
    assert client.get("/api/stats").json()["drafts"] == 0
    assert client.get("/api/personas").json()["personas"] == []
