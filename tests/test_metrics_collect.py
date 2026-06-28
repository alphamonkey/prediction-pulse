"""Tests for the metrics collect cycle: poll account + post engagement, persist, idempotently."""

from datetime import datetime, timezone

import pytest

from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.metrics.collect import MetricsJob, MetricsReport, collect_once
from pulse.metrics.dryrun import NullEngagementSource
from pulse.publish.base import PostResult
from pulse.scheduler.base import Job
from pulse.store.db import Database

_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    database.insert_post("k1", "gnome",
                         PostResult(channel="bluesky", posted=True, uri="at://1", cid="c", text="hi"))
    yield database
    database.close()


class FakeSource:
    """A real-ish engagement source with a metric set that includes impressions (unlike Bluesky)."""

    name = "bluesky"
    supported_metrics = frozenset({MetricKind.LIKES, MetricKind.IMPRESSIONS})

    def __init__(self):
        self.account_calls = 0

    def account(self, handle):
        self.account_calls += 1
        return AccountStats(followers=50, follows=10, posts=5, fetched_at=_NOW)

    def engagement(self, uris):
        return [PostEngagement(u, "bluesky", _NOW,
                               {MetricKind.LIKES: 5, MetricKind.IMPRESSIONS: 100}) for u in uris]


def test_collect_once_persists_account_and_metrics(db):
    report = collect_once(db, FakeSource(), handle="gnome.bsky.social", post_limit=50)
    assert isinstance(report, MetricsReport)
    assert report.followers == 50
    assert report.posts_measured == 1
    assert db.follower_series()[-1]["followers"] == 50
    assert db.kpms()["applause"] == 5.0


def test_collect_once_is_idempotent_for_post_metrics(db):
    collect_once(db, FakeSource(), handle="h", post_limit=50)
    collect_once(db, FakeSource(), handle="h", post_limit=50)
    # post metrics upsert in place (no dup rows); account snapshots append (a time-series).
    assert db.conn.execute("SELECT COUNT(*) FROM post_metrics").fetchone()[0] == 2  # likes+impressions
    assert db.conn.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 2


def test_collect_generalizes_to_a_richer_metric_set(db):
    # A source exposing impressions (which Bluesky lacks) flows end-to-end and unlocks a true rate.
    collect_once(db, FakeSource(), handle="h", post_limit=50)
    k = db.kpms()
    assert k["total_engagements"] == 5          # impressions are passive, excluded
    assert k["engagement_rate"] == pytest.approx(5.0)  # 5 / 100 * 100


def test_collect_once_inert_source_writes_nothing(db):
    report = collect_once(db, NullEngagementSource("bluesky"), handle="h", post_limit=50)
    assert report == MetricsReport()
    assert db.conn.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 0
    assert db.conn.execute("SELECT COUNT(*) FROM post_metrics").fetchone()[0] == 0


def test_metrics_job_is_a_named_job(db):
    job = MetricsJob(db, FakeSource(), handle="h", post_limit=50)
    assert job.name == "metrics"
    assert isinstance(job, Job)
    report = job.run()
    assert report.followers == 50
