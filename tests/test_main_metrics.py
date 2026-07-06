"""CLI wiring tests for `pulse metrics` (collaborators faked, mirrors the publish-command tests)."""

from types import SimpleNamespace

from pulse import config, main


def _metrics_fakes(monkeypatch, calls):
    class FakeDB:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            calls["connected"] = True

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "make_engagement_source",
                        lambda platform: SimpleNamespace(name=platform))


def test_metrics_one_shot(monkeypatch):
    calls = {}
    _metrics_fakes(monkeypatch, calls)

    class FakeJob:
        name = "metrics"

        def __init__(self, db, source, *, handle, post_limit):
            calls["platform"] = source.name
            calls["handle"] = handle
            calls["post_limit"] = post_limit

        def run(self):
            calls["ran"] = True

    monkeypatch.setattr(main, "MetricsJob", FakeJob)
    monkeypatch.setenv("BLUESKY_HANDLE", "gnome.bsky.social")
    # A persona with no channels falls back to the global handle (and pins the test
    # against whatever PULSE_PERSONA the ambient .env selects).
    from pulse.persona import Persona
    monkeypatch.setattr(main, "load_persona",
                        lambda name: Persona(name=name, voice="v", channels=[]))

    main.cli(["metrics", "--limit", "7"])

    assert calls["platform"] == "bluesky"
    assert calls["handle"] == "gnome.bsky.social"
    assert calls["post_limit"] == 7
    assert calls["ran"] is True
    assert calls["closed"] is True


def test_metrics_defaults_limit_from_config(monkeypatch):
    calls = {}
    _metrics_fakes(monkeypatch, calls)
    monkeypatch.setattr(main, "MetricsJob",
                        lambda db, source, *, handle, post_limit: SimpleNamespace(
                            name="metrics", run=lambda: calls.update(post_limit=post_limit)))

    main.cli(["metrics"])
    assert calls["post_limit"] == config.METRICS_POST_WINDOW


def test_metrics_loop_drives_scheduler(monkeypatch):
    calls = {}
    _metrics_fakes(monkeypatch, calls)

    from pulse.metrics.collect import MetricsJob

    monkeypatch.setattr(main, "MetricsJob",
                        lambda db, source, *, handle, post_limit: SimpleNamespace(name="metrics"))

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


def test_metrics_uses_the_personas_channel_handle_and_db(monkeypatch):
    calls = {}
    _metrics_fakes(monkeypatch, calls)

    class PathDB:
        def __init__(self, path, *a, **k):
            calls["db_path"] = path

        def connect(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(main, "Database", PathDB)
    monkeypatch.setattr(
        main, "MetricsJob",
        lambda db, source, *, handle, post_limit: SimpleNamespace(
            name="metrics", run=lambda: calls.update(handle=handle)))
    from pulse.persona import Persona
    monkeypatch.setattr(main, "load_persona", lambda name: Persona(
        name=name, voice="v",
        channels=[{"platform": "bluesky", "handle": f"{name}.bsky.social"}]))
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    monkeypatch.delenv("PULSE_DB_PATH", raising=False)

    main.cli(["metrics", "--persona", "alpha"])
    assert calls["handle"] == "alpha.bsky.social"
    assert calls["db_path"] == config.db_path_for("alpha")
    assert calls["db_path"].endswith("alpha.db")
