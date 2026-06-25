from datetime import datetime, timedelta, timezone

import pytest

from pulse.models import Snapshot, ValueKind
from pulse.poller import PollJob, PollReport, poll_once
from pulse.scheduler.base import Job
from pulse.store.db import Database

_T = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


class FakeSource:
    """A SnapshotSource that returns a fixed list regardless of `now`."""

    venue = "kalshi"

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def fetch_snapshots(self, now):
        return self._snapshots


def _snap(ts, value):
    return Snapshot("kalshi", "A", ts, value, ValueKind.PROBABILITY)


def test_poll_once_stores_snapshots_and_detects(db):
    # Two readings of market A: +15pts, crosses no milestone -> one odds_swing.
    source = FakeSource([_snap(_T, 0.55), _snap(_T + timedelta(minutes=10), 0.70)])
    report = poll_once(source, db)
    assert isinstance(report, PollReport)
    assert report.markets_seen == 2
    assert report.snapshots_stored == 2
    assert [e.rule for e in report.events] == ["odds_swing"]


def test_poll_once_is_idempotent_on_repeat(db):
    snaps = [_snap(_T, 0.55), _snap(_T + timedelta(minutes=10), 0.70)]
    poll_once(FakeSource(snaps), db)
    report = poll_once(FakeSource(snaps), db)  # identical data again
    assert report.snapshots_stored == 0   # nothing new ingested
    assert report.events == []            # dedup backstop -> no re-fire


def test_polljob_is_a_named_job():
    job = PollJob(FakeSource([]), None)
    assert job.name == "poll"
    assert isinstance(job, Job)


def test_polljob_run_polls_and_returns_report(db):
    source = FakeSource([_snap(_T, 0.55), _snap(_T + timedelta(minutes=10), 0.70)])
    report = PollJob(source, db).run()
    assert isinstance(report, PollReport)
    assert report.markets_seen == 2
    assert report.snapshots_stored == 2
    assert [e.rule for e in report.events] == ["odds_swing"]
