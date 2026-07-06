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
