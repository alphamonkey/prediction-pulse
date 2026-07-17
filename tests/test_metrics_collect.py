"""Tests for the metrics collect cycle: poll account + post engagement, persist, idempotently."""

from datetime import datetime, timezone

import pytest

from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.metrics.collect import MetricsJob, MetricsReport, collect_once
from pulse.metrics.dryrun import NullEngagementSource
from pulse.persona import Persona
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


# ── MetricsJob: a per-channel loop, like PublishJob and EngageJob ──
# collect_once (above) keeps its exact single-source signature — that seam is untouched, which is
# what lets the tests above stand unchanged.

class _MastoSource:
    name = "mastodon"
    supported_metrics = frozenset({MetricKind.LIKES})

    def __init__(self):
        self.handles = []

    def account(self, handle):
        self.handles.append(handle)
        return AccountStats(followers=400, follows=20, posts=30, fetched_at=_NOW)

    def engagement(self, uris):
        return [PostEngagement(u, "mastodon", _NOW, {MetricKind.LIKES: 9}) for u in uris]


def _persona(*channels):
    return Persona(name="gnome", voice="v", channels=list(channels))


def test_metrics_job_is_a_named_job(db, monkeypatch):
    monkeypatch.setattr("pulse.metrics.collect.make_engagement_source",
                        lambda channel: FakeSource())
    job = MetricsJob(db, _persona({"platform": "bluesky", "handle": "h"}), post_limit=50)
    assert job.name == "metrics"
    assert isinstance(job, Job)
    assert job.run().followers == 50


def test_metrics_job_collects_each_channel_with_that_channels_own_handle(db, monkeypatch):
    db.insert_post("k2", "gnome",
                   PostResult(channel="mastodon", posted=True, uri="108", cid=None, text="hi"))
    bsky, masto = FakeSource(), _MastoSource()
    monkeypatch.setattr("pulse.metrics.collect.make_engagement_source",
                        lambda channel: masto if channel["platform"] == "mastodon" else bsky)

    persona = _persona({"platform": "bluesky", "handle": "gnome.bsky.social"},
                       {"platform": "mastodon", "instance": "https://m.example",
                        "handle": "@gnome@m.example"})
    report = MetricsJob(db, persona, post_limit=50).run()

    assert masto.handles == ["@gnome@m.example"]   # not the Bluesky handle
    assert report.by_platform == {"bluesky": 50, "mastodon": 400}
    assert report.posts_measured == 2              # one post per channel
    # One account snapshot per platform, each attributed to its own account.
    rows = db.conn.execute(
        "SELECT platform, followers FROM account_snapshots ORDER BY platform").fetchall()
    assert [(r["platform"], r["followers"]) for r in rows] == [("bluesky", 50), ("mastodon", 400)]


def test_metrics_job_with_no_channels_collects_nothing(db):
    """It used to fall back to the global BLUESKY_HANDLE and collect anyway — for an account the
    persona never declared."""
    report = MetricsJob(db, _persona(), post_limit=50).run()
    assert report == MetricsReport()
    assert db.conn.execute("SELECT COUNT(*) FROM account_snapshots").fetchone()[0] == 0
