"""Tests for the publish orchestrator: select unposted drafts -> publish -> record."""

from datetime import datetime, timezone

import pytest

from pulse import config
from pulse.persona import Persona
from pulse.publisher import PublishJob, PublishReport, publish_once
from pulse.publish.base import PostResult
from pulse.scheduler.base import Job
from pulse.store.db import Database
from pulse.writer.base import Draft

_PERSONA = Persona(name="gnome", voice="be a gnome",
                   channels=[{"platform": "bluesky"}])


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _seed_drafts(db, n, persona="gnome"):
    now = datetime.now(timezone.utc)
    for i in range(n):
        db.insert_draft(Draft(event_dedup_key=f"k{i}", persona=persona,
                              text=f"post {i}", created_at=now))


class FakePublisher:
    """A real-posting publisher stub (records what it published)."""

    name = "bluesky"

    def __init__(self):
        self.published = []

    def publish(self, draft, persona):
        self.published.append(draft.event_dedup_key)
        return PostResult(channel="bluesky", posted=True,
                          uri=f"at://{draft.event_dedup_key}", cid="c", text=draft.text)


def test_publish_once_posts_and_records(db):
    _seed_drafts(db, 3)
    pub = FakePublisher()
    report = publish_once(db, pub, _PERSONA, limit=5)
    assert isinstance(report, PublishReport)
    assert report.posted == 3
    assert len(pub.published) == 3
    assert db.posts_today("bluesky") == 3


def test_publish_once_is_idempotent_on_repeat(db):
    _seed_drafts(db, 2)
    publish_once(db, FakePublisher(), _PERSONA, limit=5)
    pub = FakePublisher()
    report = publish_once(db, pub, _PERSONA, limit=5)  # all already posted
    assert report.posted == 0
    assert pub.published == []


def test_publish_once_respects_daily_cap(db, monkeypatch):
    monkeypatch.setattr(config, "MAX_POSTS_PER_DAY", 2)
    _seed_drafts(db, 5)
    report = publish_once(db, FakePublisher(), _PERSONA, limit=5)
    assert report.posted == 2          # capped
    assert db.posts_today("bluesky") == 2


def test_publish_once_does_not_drain_the_daily_quota_in_one_cycle(db):
    """The per-cycle limit is NOT the daily cap. Defaulting one to the other let a single cycle
    post the whole day's quota back-to-back — live, that was 9 posts inside one second."""
    _seed_drafts(db, config.MAX_POSTS_PER_DAY)
    pub = FakePublisher()

    report = publish_once(db, pub, _PERSONA, limit=config.POSTS_PER_CYCLE)

    assert config.POSTS_PER_CYCLE < config.MAX_POSTS_PER_DAY
    assert report.posted == config.POSTS_PER_CYCLE
    assert db.posts_today("bluesky") < config.MAX_POSTS_PER_DAY  # room left for later cycles


def test_publish_once_dryrun_records_nothing(db):
    _seed_drafts(db, 2)

    class DryPub:
        name = "bluesky"

        def publish(self, draft, persona):
            return PostResult(channel="bluesky", posted=False, text=draft.text)

    report = publish_once(db, DryPub(), _PERSONA, limit=5)
    assert report.would_post == 2
    assert report.posted == 0
    assert db.posts_today("bluesky") == 0  # dryrun leaves no posts -> live posts fresh later


def test_publish_job_is_a_named_job_and_loops_channels(db, monkeypatch):
    _seed_drafts(db, 1)
    pub = FakePublisher()
    monkeypatch.setattr("pulse.publisher.make_publisher", lambda channel: pub)

    job = PublishJob(db, _PERSONA, limit=5)
    assert job.name == "publish"
    assert isinstance(job, Job)
    report = job.run()
    assert report.posted == 1
    assert pub.published == ["k0"]
