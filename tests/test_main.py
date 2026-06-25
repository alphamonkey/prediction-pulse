from pulse import main


def _fakes(monkeypatch, calls):
    """Patch out the network/db collaborators so CLI wiring can be tested in isolation."""

    class FakeDB:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            calls["db_connected"] = True

        def close(self):
            calls["db_closed"] = True

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def close(self):
            calls["client_closed"] = True

    class FakeJob:
        name = "poll"

        def __init__(self, source, db):
            calls["venue"] = source.venue

        def run(self):
            calls["job_ran"] = calls.get("job_ran", 0) + 1

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "KalshiClient", FakeClient)
    monkeypatch.setattr(main, "PollJob", FakeJob)
    return FakeJob


def test_poll_command_runs_job_once(monkeypatch):
    calls = {}
    _fakes(monkeypatch, calls)

    main.cli(["poll"])

    assert calls["db_connected"] is True
    assert calls["venue"] == "kalshi"
    assert calls["job_ran"] == 1
    assert calls["client_closed"] is True
    assert calls["db_closed"] is True


def test_run_command_drives_the_scheduler(monkeypatch):
    calls = {}
    FakeJob = _fakes(monkeypatch, calls)

    class FakeScheduler:
        def __init__(self, job, interval_seconds, *, max_iterations=0):
            calls["job_is_polljob"] = isinstance(job, FakeJob)
            calls["interval"] = interval_seconds
            calls["max_iterations"] = max_iterations

        def run(self, stop=None):
            calls["scheduler_ran"] = True

    monkeypatch.setattr(main, "IntervalScheduler", FakeScheduler)

    main.cli(["run", "--interval", "42", "--max-iterations", "3"])

    assert calls["job_is_polljob"] is True
    assert calls["interval"] == 42
    assert calls["max_iterations"] == 3
    assert calls["scheduler_ran"] is True
    assert calls["client_closed"] is True
    assert calls["db_closed"] is True


def test_run_command_defaults_interval_from_config(monkeypatch):
    calls = {}
    _fakes(monkeypatch, calls)

    class FakeScheduler:
        def __init__(self, job, interval_seconds, *, max_iterations=0):
            calls["interval"] = interval_seconds

        def run(self, stop=None):
            pass

    monkeypatch.setattr(main, "IntervalScheduler", FakeScheduler)

    main.cli(["run"])

    from pulse import config
    assert calls["interval"] == config.DEFAULT_INTERVAL_SECONDS


from types import SimpleNamespace  # noqa: E402

from pulse import config  # noqa: E402
from pulse.drafter import DraftReport  # noqa: E402


def _draft_fakes(monkeypatch, calls):
    class FakeDB:
        def __init__(self, *a, **k):
            pass

        def connect(self):
            calls["connected"] = True

        def close(self):
            calls["closed"] = True

    def fake_draft_once(db, writer, persona, *, limit):
        calls["limit"] = limit
        calls["persona"] = persona.name
        calls["writer"] = writer.name
        return DraftReport(candidates=3, drafted=2)

    monkeypatch.setattr(main, "Database", FakeDB)
    monkeypatch.setattr(main, "make_writer", lambda: SimpleNamespace(name="fake"))
    monkeypatch.setattr(main, "load_persona", lambda name: SimpleNamespace(name=name))
    monkeypatch.setattr(main, "draft_once", fake_draft_once)


def test_draft_command_runs_pipeline(monkeypatch):
    calls = {}
    _draft_fakes(monkeypatch, calls)

    main.cli(["draft", "--limit", "2", "--persona", "alpha"])

    assert calls["connected"] is True
    assert calls["writer"] == "fake"
    assert calls["persona"] == "alpha"
    assert calls["limit"] == 2
    assert calls["closed"] is True


def test_draft_command_defaults_from_config(monkeypatch):
    calls = {}
    _draft_fakes(monkeypatch, calls)

    main.cli(["draft"])

    assert calls["limit"] == config.DRAFTS_PER_RUN
    assert calls["persona"] == config.PERSONA


def test_serve_command_invokes_server(monkeypatch):
    calls = {}
    import pulse.server.app as serverapp
    monkeypatch.setattr(serverapp, "serve", lambda host, port: calls.update(host=host, port=port))

    main.cli(["serve", "--host", "0.0.0.0", "--port", "9999"])

    assert calls == {"host": "0.0.0.0", "port": 9999}


def test_serve_command_defaults_from_config(monkeypatch):
    calls = {}
    import pulse.server.app as serverapp
    monkeypatch.setattr(serverapp, "serve", lambda host, port: calls.update(host=host, port=port))

    main.cli(["serve"])

    assert calls["host"] == config.DASHBOARD_HOST
    assert calls["port"] == config.DASHBOARD_PORT
