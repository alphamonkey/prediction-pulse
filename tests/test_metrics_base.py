"""Tests for the metrics seam vocabulary, dataclasses, and EngagementSource Protocol.

The seam must generalize across platforms with different metric sets — Bluesky exposes a few
counts, X/Twitter a superset — so per-post data is a metric *bag* keyed by a normalized vocabulary,
and each source declares which metrics it supports.
"""

from datetime import datetime, timezone

from pulse.metrics.base import (
    AccountStats,
    EngagementSource,
    MetricKind,
    PostEngagement,
)

_T = datetime(2026, 6, 27, 12, 0, 0, tzinfo=timezone.utc)


def test_metric_kind_is_a_normalized_string_vocabulary():
    # Stored/serialized as plain strings; spans more than Bluesky's set so richer sources fit.
    assert MetricKind.LIKES.value == "likes"
    assert MetricKind.IMPRESSIONS.value == "impressions"
    assert isinstance(MetricKind.LIKES, str)
    names = {m.value for m in MetricKind}
    assert {"likes", "reposts", "replies", "quotes", "impressions"} <= names


def test_account_stats_holds_universal_counts():
    a = AccountStats(followers=120, follows=80, posts=42, fetched_at=_T)
    assert (a.followers, a.follows, a.posts, a.fetched_at) == (120, 80, 42, _T)


def test_post_engagement_is_a_metric_bag():
    e = PostEngagement(
        uri="at://did/1", platform="bluesky", fetched_at=_T,
        metrics={MetricKind.LIKES: 5, MetricKind.REPLIES: 2},
    )
    assert e.metrics[MetricKind.LIKES] == 5
    assert MetricKind.IMPRESSIONS not in e.metrics  # platforms report only what they have


def test_engagement_source_protocol_conformance():
    class StubSource:
        name = "stub"
        supported_metrics = frozenset({MetricKind.LIKES})

        def account(self, handle):
            return AccountStats(0, 0, 0, _T)

        def engagement(self, uris):
            return []

    assert isinstance(StubSource(), EngagementSource)


def test_non_conforming_object_is_not_a_source():
    class NotASource:
        name = "x"

    assert not isinstance(NotASource(), EngagementSource)
