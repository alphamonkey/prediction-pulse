"""Chunk 4: `pulse poll/run --source {kalshi,trend}` wiring."""

from __future__ import annotations

from pulse import main


class FakeDB:
    def __init__(self, *a, **k):
        pass

    def connect(self):
        pass

    def close(self):
        pass


class FakeKalshiClient:
    def __init__(self, *a, **k):
        pass

    def close(self):
        pass


def _setup(monkeypatch, captured):
    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "KalshiClient", FakeKalshiClient)

    class FakeJob:
        name = "poll"

        def __init__(self, source, db):
            captured["src"] = type(source).__name__

        def run(self):
            captured["ran"] = True

    monkeypatch.setattr(main, "PollJob", FakeJob)


def test_poll_default_source_is_kalshi(monkeypatch):
    c = {}
    _setup(monkeypatch, c)
    main.cli(["poll"])
    assert c["src"] == "KalshiSource"
    assert c["ran"] is True


def test_poll_source_trend_builds_trend_source(monkeypatch):
    c = {}
    _setup(monkeypatch, c)
    main.cli(["poll", "--source", "trend"])
    assert c["src"] == "BlueskyTrendSource"


def test_run_source_trend_loops_with_trend_source(monkeypatch):
    c = {}
    _setup(monkeypatch, c)

    class FakeScheduler:
        def __init__(self, job, interval_seconds, *, max_iterations=0, jitter_seconds=0):
            c["interval"] = interval_seconds

        def run(self, stop=None):
            c["ran"] = True

    monkeypatch.setattr(main, "IntervalScheduler", FakeScheduler)

    main.cli(["run", "--source", "trend", "--interval", "900", "--max-iterations", "1"])

    assert c["src"] == "BlueskyTrendSource"
    assert c["interval"] == 900
    assert c["ran"] is True
