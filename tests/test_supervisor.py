"""The persona supervisor: one process runs everything a persona's [pipeline] declares.

build_supervised is pure assembly (spec → jobs + schedulers) and is tested against the real
factories in dryrun mode — constructing jobs never touches the network; only .run() would.
supervise() drives the schedulers on threads sharing one stop Event. Every job gets its OWN
Database connection (WAL + busy_timeout serialize across connections, as in the old
process-per-stage layout) — sharing one connection across job threads let an in-flight cursor
on one thread break prune's wal_checkpoint on another (seen live at the gnome cutover).
"""

from __future__ import annotations

import threading

import pytest

from pulse.engage.base import SignalKind
from pulse.persona import Persona
from pulse.pipeline import parse_pipeline
from pulse.scheduler.interval import IntervalScheduler
from pulse.scheduler.windowed import WindowedScheduler
from pulse.store.db import Database
from pulse.supervisor import build_supervised, supervise


def _persona(pipeline: dict, channels: list | None = None) -> Persona:
    return Persona(
        name="testp",
        voice="You are a test voice.",
        channels=channels if channels is not None else [
            {"platform": "bluesky", "handle": "testp.bsky.social"}],
        pipeline=parse_pipeline(pipeline),
    )


@pytest.fixture
def db(tmp_path):
    """A make-db factory: one fresh connection to the persona's file per call."""
    path = str(tmp_path / "testp.db")
    made = []

    def make_db() -> Database:
        database = Database(path)
        database.connect()
        made.append(database)
        return database

    yield make_db
    for database in made:
        database.close()


@pytest.fixture(autouse=True)
def dryrun_env(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


FULL = {
    "poll": {"sources": ["trend"], "interval": 900},
    "draft": {"interval": 3600},
    "publish": {"interval": 14400, "windows": [["07:00", "10:00"]]},
    "engage": {"interval": 3600, "windows": "publish", "actions": ["like"],
               "caps": {"like": 3}},
    "metrics": {"interval": 3600},
}


def test_build_maps_sections_to_jobs(db):
    entries = build_supervised(_persona(FULL), db, kalshi_client=object())
    by_name = {e.name: e for e in entries}
    assert set(by_name) == {"poll:trend", "draft", "publish", "engage", "metrics", "prune"}
    # Outward actions are dayparted; everything else runs 24/7.
    assert isinstance(by_name["publish"].scheduler, WindowedScheduler)
    assert isinstance(by_name["engage"].scheduler, WindowedScheduler)
    for name in ("poll:trend", "draft", "metrics", "prune"):
        assert isinstance(by_name[name].scheduler, IntervalScheduler)


def test_build_one_poll_job_per_source(db):
    persona = _persona({"poll": {"sources": ["kalshi", "trend"]}})
    names = {e.name for e in build_supervised(persona, db, kalshi_client=object())}
    assert {"poll:kalshi", "poll:trend"} <= names


def test_build_unknown_source_rejected(db):
    persona = _persona({"poll": {"sources": ["rss"]}})
    with pytest.raises(ValueError, match="rss"):
        build_supervised(persona, db, kalshi_client=object())


def test_prune_is_always_scheduled(db):
    entries = build_supervised(_persona({"metrics": {}}), db)
    assert {e.name for e in entries} == {"metrics", "prune"}


def test_metrics_handle_comes_from_persona_channel(db, monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    entries = build_supervised(_persona({"metrics": {}}), db)
    metrics = next(e for e in entries if e.name == "metrics")
    assert metrics.job._handle == "testp.bsky.social"


def test_metrics_handle_falls_back_to_global(db, monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    entries = build_supervised(_persona({"metrics": {}}, channels=[]), db)
    metrics = next(e for e in entries if e.name == "metrics")
    assert metrics.job._handle == "global.bsky.social"


def test_engage_policy_built_from_spec(db):
    entries = build_supervised(_persona(FULL), db, kalshi_client=object())
    engage = next(e for e in entries if e.name == "engage")
    policy = engage.job._policy
    assert policy.actions == (SignalKind.LIKE,)
    assert policy.caps[SignalKind.LIKE] == 3
    assert policy.queries  # defaults flow through


def test_each_job_gets_its_own_connection(db):
    # One shared connection across job threads is how prune's wal_checkpoint broke live:
    # another thread's in-flight cursor makes the checkpoint raise "database table is locked".
    entries = build_supervised(_persona(FULL), db, kalshi_client=object())
    ids = [id(e.db) for e in entries]
    assert len(set(ids)) == len(entries)
    assert all(e.db.conn is not None for e in entries)


def test_supervise_runs_every_job_once_and_returns(tmp_path):
    # windows = [] means always-on, so max_iterations=1 lets the windowed jobs cycle too.
    persona = _persona({
        "draft": {"interval": 1},
        "publish": {"interval": 1, "windows": []},
        "metrics": {"interval": 1},
    })
    supervise(persona, tmp_path / "testp.db", max_iterations=1)  # returns when all finish


def test_supervise_honors_stop_event(tmp_path):
    persona = _persona({"metrics": {"interval": 3600}})
    stop = threading.Event()
    t = threading.Thread(target=supervise, args=(persona, tmp_path / "testp.db"),
                         kwargs={"stop": stop}, daemon=True)
    t.start()
    stop.set()
    t.join(timeout=5)
    assert not t.is_alive()
