from datetime import datetime, timedelta, timezone

import pytest

from pulse.models import Event, Snapshot, ValueKind
from pulse.poller import PollJob, PollReport, poll_once
from pulse.scheduler.base import Job
from pulse.store.db import Database
from pulse.venue.base import SnapshotContentSource

_T = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


class FakeSnapshots:
    """A SnapshotSource that returns a fixed list regardless of `now`."""

    venue = "kalshi"

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def fetch_snapshots(self, now):
        return self._snapshots


class FakeContentSource:
    """A non-market ContentSource honoring the contract: record, return only the new ones."""

    venue = "fake"

    def __init__(self, events):
        self._events = events

    def fetch_events(self, db, now):
        return [e for e in self._events if db.record_posted(e)]


def _snap(ts, value):
    return Snapshot("kalshi", "A", ts, value, ValueKind.PROBABILITY)


def _swing_source():
    # Two readings of market A: +15pts, crosses no milestone -> one odds_swing.
    return SnapshotContentSource(
        FakeSnapshots([_snap(_T, 0.55), _snap(_T + timedelta(minutes=10), 0.70)]))


def _event(dedup_key="generated:beans:2026-06-24T00"):
    return Event(
        rule="generated", venue="fake", market_id="beans", ts=_T, value_kind=None,
        from_value=None, to_value=None, magnitude=1.0, direction=None,
        headline="Topic: beans", dedup_key=dedup_key,
    )


def test_poll_once_reports_snapshot_source_events(db):
    report = poll_once(_swing_source(), db)
    assert isinstance(report, PollReport)
    assert [e.rule for e in report.events] == ["odds_swing"]


def test_poll_once_is_idempotent_on_repeat(db):
    poll_once(_swing_source(), db)
    report = poll_once(_swing_source(), db)  # identical data again
    assert report.events == []  # dedup backstop -> no re-fire


def test_poll_once_accepts_any_content_source(db):
    report = poll_once(FakeContentSource([_event()]), db)
    assert [e.headline for e in report.events] == ["Topic: beans"]
    assert db.has_posted("generated:beans:2026-06-24T00")
    # Same dedup_key next cycle -> already recorded -> not reported again.
    assert poll_once(FakeContentSource([_event()]), db).events == []


def test_polljob_is_a_named_job():
    job = PollJob(FakeContentSource([]), None)
    assert job.name == "poll"
    assert isinstance(job, Job)


def test_polljob_run_polls_and_returns_report(db):
    report = PollJob(_swing_source(), db).run()
    assert isinstance(report, PollReport)
    assert [e.rule for e in report.events] == ["odds_swing"]
