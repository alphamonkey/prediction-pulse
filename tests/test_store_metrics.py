"""Tests for the engagement-metrics store layer: account snapshots, post-metric upserts, and the
KPM reads the dashboard renders. Metrics are stored *tall* (one row per uri+metric) so platforms
with different metric sets need no schema change; per-post counts are latest-only (no time-series).
"""

from datetime import datetime, timedelta, timezone

import pytest

from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.publish.base import PostResult
from pulse.store.db import Database

_NOW = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _post(db, uri, text, *, channel="bluesky"):
    db.insert_post("k-" + uri, "gnome",
                   PostResult(channel=channel, posted=True, uri=uri, cid="c", text=text))


def _eng(uri, metrics, *, platform="bluesky", ts=_NOW):
    return PostEngagement(uri=uri, platform=platform, fetched_at=ts,
                          metrics={MetricKind(k): v for k, v in metrics.items()})


# ── account snapshots / follower growth ──

def test_account_snapshot_and_follower_series(db):
    db.insert_account_snapshot(AccountStats(100, 50, 10, _NOW - timedelta(days=8)))
    db.insert_account_snapshot(AccountStats(110, 55, 12, _NOW - timedelta(days=3)))
    db.insert_account_snapshot(AccountStats(120, 60, 15, _NOW))
    series = db.follower_series(days=30, now=_NOW)  # pin the window so the test can't rot
    assert [p["followers"] for p in series] == [100, 110, 120]  # ascending by ts


def test_recent_post_uris_filters_channel_and_nulls(db):
    _post(db, "at://1", "alpha")
    _post(db, "at://2", "beta")
    _post(db, "at://x", "other", channel="x")
    db.insert_post("k-null", "gnome",
                   PostResult(channel="bluesky", posted=True, uri=None, cid=None, text="n"))
    assert set(db.recent_post_uris("bluesky", limit=10)) == {"at://1", "at://2"}


# ── post-metric upserts ──

def test_upsert_post_metrics_overwrites_latest(db):
    db.upsert_post_metrics([_eng("at://1", {"likes": 10})])
    db.upsert_post_metrics([_eng("at://1", {"likes": 99})])  # latest wins, no second row
    row = db.conn.execute(
        "SELECT value, COUNT(*) n FROM post_metrics WHERE uri='at://1' AND metric='likes'"
    ).fetchone()
    assert (row["value"], row["n"]) == (99, 1)


# ── KPMs ──

def _seed_kpm(db):
    db.insert_account_snapshot(AccountStats(100, 50, 10, _NOW - timedelta(days=3)))
    db.insert_account_snapshot(AccountStats(120, 60, 15, _NOW))
    _post(db, "at://1", "alpha")
    _post(db, "at://2", "beta")
    db.upsert_post_metrics([
        _eng("at://1", {"likes": 10, "reposts": 2, "replies": 1, "quotes": 0}),
        _eng("at://2", {"likes": 4, "reposts": 0, "replies": 3, "quotes": 1}),
    ])


def test_kpms_core_rates(db):
    _seed_kpm(db)
    k = db.kpms(now=_NOW)  # pin the 7-day window so the test can't rot as wall-clock time passes
    assert k["followers"] == 120
    assert k["follower_delta_7d"] == 20      # 120 - earliest-within-7d (100)
    assert k["posts_measured"] == 2
    assert k["applause"] == 7.0              # avg likes (14/2)
    assert k["conversation"] == 2.0          # avg replies (4/2)
    assert k["amplification"] == 1.5         # avg reposts (1.0) + avg quotes (0.5)
    assert k["total_engagements"] == 21      # 14+2+4+1
    assert "engagement_rate" not in k        # no impressions -> no true rate


def test_kpms_engagement_rate_only_with_impressions(db):
    _seed_kpm(db)
    db.upsert_post_metrics([
        _eng("at://1", {"impressions": 1000}),
        _eng("at://2", {"impressions": 1000}),
    ])
    k = db.kpms()
    assert k["total_engagements"] == 21      # impressions are passive, excluded from engagements
    assert k["engagement_rate"] == pytest.approx(1.05)  # 21 / 2000 * 100


def test_kpms_empty_db_is_safe(db):
    k = db.kpms()
    assert k["followers"] is None
    assert k["posts_measured"] == 0
    assert k["applause"] == 0
    assert k["total_engagements"] == 0
    assert "engagement_rate" not in k


def test_top_posts_orders_by_total_engagement(db):
    _seed_kpm(db)
    top = db.top_posts(limit=5)
    assert [p["uri"] for p in top] == ["at://1", "at://2"]  # 13 vs 8 total
    assert top[0]["text"] == "alpha"
    assert top[0]["total"] == 13
    assert top[0]["metrics"]["likes"] == 10
