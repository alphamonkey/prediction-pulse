"""Chunk 6: `pulse engage` CLI wiring."""

from __future__ import annotations

from types import SimpleNamespace

from pulse import config, main


def _engage_fakes(monkeypatch, calls):
    class FakeDB:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            calls["connected"] = True

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "load_persona",
                        lambda name: SimpleNamespace(name=name, channels=[]))


def test_engage_one_shot(monkeypatch):
    calls = {}
    _engage_fakes(monkeypatch, calls)

    from pulse.engager import EngageReport

    class FakeJob:
        name = "engage"

        def __init__(self, db, persona, policy, *, limit):
            calls["persona"] = persona.name
            calls["limit"] = limit
            calls["policy"] = policy

        def run(self):
            calls["ran"] = True
            return EngageReport()

    monkeypatch.setattr(main, "EngageJob", FakeJob)

    main.cli(["engage", "--persona", "gnome", "--limit", "7"])

    assert calls["persona"] == "gnome"
    assert calls["limit"] == 7
    assert calls["ran"] is True
    assert calls["closed"] is True
    # the policy was built from config
    assert calls["policy"].queries == list(config.ENGAGE_QUERIES)


def test_engage_defaults_from_config(monkeypatch):
    calls = {}
    _engage_fakes(monkeypatch, calls)

    class FakeJob:
        name = "engage"

        def __init__(self, db, persona, policy, *, limit):
            calls["limit"] = limit
            calls["persona"] = persona.name

        def run(self):
            return None

    monkeypatch.setattr(main, "EngageJob", FakeJob)

    main.cli(["engage"])

    assert calls["limit"] == config.ENGAGE_TARGETS_PER_RUN
    assert calls["persona"] == config.PERSONA


def test_engage_loop_drives_scheduler(monkeypatch):
    calls = {}
    _engage_fakes(monkeypatch, calls)

    from pulse.engager import EngageJob

    class FakeWindowed:
        def __init__(self, job, interval_seconds, *, windows, tz, max_iterations=0,
                     jitter_seconds=0):
            calls["jitter"] = jitter_seconds
            calls["job_name"] = job.name
            calls["is_engagejob"] = isinstance(job, EngageJob)
            calls["interval"] = interval_seconds
            calls["max_iterations"] = max_iterations
            calls["windows"] = windows
            calls["tz"] = tz

        def run(self, stop=None):
            calls["scheduler_ran"] = True

    monkeypatch.setattr(main, "WindowedScheduler", FakeWindowed)

    main.cli(["engage", "--interval", "3600", "--max-iterations", "1", "--jitter", "120"])

    assert calls["job_name"] == "engage"
    assert calls["is_engagejob"] is True
    assert calls["interval"] == 3600
    assert calls["jitter"] == 120
    assert calls["windows"] == config.ENGAGE_WINDOWS  # engager is dayparted
    assert calls["tz"] == config.ACTIVE_TZ
    assert calls["scheduler_ran"] is True
    assert calls["closed"] is True
