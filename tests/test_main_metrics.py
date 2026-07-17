"""CLI wiring tests for `pulse metrics` (collaborators faked, mirrors the publish-command tests).

MetricsJob now takes the whole persona and loops its channels (like PublishJob/EngageJob), so the
CLI's job is just to hand it the right persona and the right DB — which handle each channel's
source gets is MetricsJob's business, tested in test_metrics_collect.py.
"""

from types import SimpleNamespace

from pulse import config, main
from pulse.persona import Persona


def _fake_db(monkeypatch, calls):
    class FakeDB:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            calls["connected"] = True

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(main, "Database", FakeDB)


def _fake_persona(monkeypatch, channels):
    monkeypatch.setattr(main, "load_persona",
                        lambda name: Persona(name=name, voice="v", channels=channels))


def test_metrics_one_shot(monkeypatch):
    calls = {}
    _fake_db(monkeypatch, calls)
    _fake_persona(monkeypatch, [{"platform": "bluesky", "handle": "gnome.bsky.social"}])

    class FakeJob:
        name = "metrics"

        def __init__(self, db, persona, *, post_limit):
            calls["persona"] = persona.name
            calls["channels"] = persona.channels
            calls["post_limit"] = post_limit

        def run(self):
            calls["ran"] = True

    monkeypatch.setattr(main, "MetricsJob", FakeJob)

    main.cli(["metrics", "--persona", "gnome", "--limit", "7"])

    assert calls["persona"] == "gnome"
    assert calls["channels"] == [{"platform": "bluesky", "handle": "gnome.bsky.social"}]
    assert calls["post_limit"] == 7
    assert calls["ran"] is True
    assert calls["closed"] is True


def test_metrics_defaults_limit_from_config(monkeypatch):
    calls = {}
    _fake_db(monkeypatch, calls)
    _fake_persona(monkeypatch, [])
    monkeypatch.setattr(main, "MetricsJob",
                        lambda db, persona, *, post_limit: SimpleNamespace(
                            name="metrics", run=lambda: calls.update(post_limit=post_limit)))

    main.cli(["metrics"])
    assert calls["post_limit"] == config.METRICS_POST_WINDOW


def test_metrics_loop_drives_scheduler(monkeypatch):
    calls = {}
    _fake_db(monkeypatch, calls)
    _fake_persona(monkeypatch, [])
    monkeypatch.setattr(main, "MetricsJob",
                        lambda db, persona, *, post_limit: SimpleNamespace(name="metrics"))

    class FakeScheduler:
        def __init__(self, job, interval_seconds, *, max_iterations=0, jitter_seconds=0):
            calls["job_name"] = job.name
            calls["interval"] = interval_seconds
            calls["jitter"] = jitter_seconds
            calls["max_iterations"] = max_iterations

        def run(self, stop=None):
            calls["scheduler_ran"] = True

    monkeypatch.setattr(main, "IntervalScheduler", FakeScheduler)

    main.cli(["metrics", "--interval", "3600", "--max-iterations", "1", "--jitter", "120"])

    assert calls["job_name"] == "metrics"
    assert calls["interval"] == 3600
    assert calls["jitter"] == 120
    assert calls["scheduler_ran"] is True
    assert calls["closed"] is True


def test_metrics_opens_the_personas_own_db(monkeypatch):
    calls = {}

    class PathDB:
        def __init__(self, path, *a, **k):
            calls["db_path"] = path

        def connect(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(main, "Database", PathDB)
    _fake_persona(monkeypatch, [{"platform": "bluesky", "handle": "alpha.bsky.social"}])
    monkeypatch.setattr(main, "MetricsJob",
                        lambda db, persona, *, post_limit: SimpleNamespace(
                            name="metrics", run=lambda: None))
    monkeypatch.delenv("PULSE_DB_PATH", raising=False)

    main.cli(["metrics", "--persona", "alpha"])
    assert calls["db_path"] == config.db_path_for("alpha")
    assert calls["db_path"].endswith("alpha.db")
