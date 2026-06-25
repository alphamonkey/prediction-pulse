"""Tests for the drafter: select undrafted events -> write -> store (dryrun)."""

from datetime import datetime, timezone

import pytest

from pulse.drafter import DraftJob, DraftReport, draft_once
from pulse.models import Event, ValueKind
from pulse.persona import Persona
from pulse.scheduler.base import Job
from pulse.store.db import Database
from pulse.writer.base import Draft

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
_PERSONA = Persona(name="example", voice="be punchy")


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _event(rule="odds_swing", market_id="A", magnitude=0.2):
    return Event(
        rule=rule, venue="kalshi", market_id=market_id, ts=_T,
        value_kind=ValueKind.PROBABILITY, from_value=0.4, to_value=0.6,
        magnitude=magnitude, direction="up", headline=f"{market_id} moved",
        dedup_key=f"{rule}:kalshi:{market_id}:2026-06-24",
    )


class FakeWriter:
    name = "fake"

    def __init__(self):
        self.calls = 0

    def write(self, event, persona, context=None):
        self.calls += 1
        return Draft(event_dedup_key=event.dedup_key, persona=persona.name,
                     text=f"post for {event.market_id}")


def test_draft_once_selects_writes_and_stores(db):
    db.record_posted(_event(market_id="A"))
    db.record_posted(_event(market_id="B"))
    writer = FakeWriter()
    report = draft_once(db, writer, _PERSONA, limit=5)
    assert isinstance(report, DraftReport)
    assert report.drafted == 2
    assert writer.calls == 2
    assert {d["event_dedup_key"] for d in db.get_drafts()} == {
        "odds_swing:kalshi:A:2026-06-24", "odds_swing:kalshi:B:2026-06-24",
    }


def test_draft_once_respects_limit(db):
    for i in range(5):
        db.record_posted(_event(market_id=f"M{i}"))
    writer = FakeWriter()
    report = draft_once(db, writer, _PERSONA, limit=2)
    assert report.drafted == 2
    assert writer.calls == 2  # only the cap reached the writer (token budget)


def test_draft_once_is_idempotent_on_repeat(db):
    db.record_posted(_event(market_id="A"))
    draft_once(db, FakeWriter(), _PERSONA, limit=5)
    writer = FakeWriter()
    report = draft_once(db, writer, _PERSONA, limit=5)  # already drafted
    assert report.drafted == 0
    assert writer.calls == 0


def test_draft_job_is_a_named_job(db):
    job = DraftJob(db, FakeWriter(), _PERSONA, limit=3)
    assert job.name == "draft"
    assert isinstance(job, Job)
    db.record_posted(_event(market_id="A"))
    report = job.run()
    assert report.drafted == 1
