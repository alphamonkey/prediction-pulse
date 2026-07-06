"""Tests for the EngagementSource implementations and the make_engagement_source live gate."""

from types import SimpleNamespace

import pytest

from pulse import config
from pulse.metrics.base import AccountStats, EngagementSource, MetricKind, PostEngagement
from pulse.metrics.bluesky import BlueskyEngagementSource
from pulse.metrics.dryrun import NullEngagementSource
from pulse.metrics.factory import make_engagement_source


# ── fake atproto client ──

class FakeBskyClient:
    def __init__(self):
        self.logged_in = None
        self.get_posts_calls = []
        self.profile_actor = None

    def login(self, login, password):
        self.logged_in = (login, password)

    def get_profile(self, actor):
        self.profile_actor = actor
        return SimpleNamespace(followers_count=120, follows_count=80, posts_count=42)

    def get_posts(self, uris):
        self.get_posts_calls.append(list(uris))
        posts = [SimpleNamespace(uri=u, like_count=1, repost_count=2, reply_count=3, quote_count=4)
                 for u in uris]
        return SimpleNamespace(posts=posts)


# ── BlueskyEngagementSource ──

def test_bluesky_source_is_a_conforming_source():
    src = BlueskyEngagementSource("h", "p", client=FakeBskyClient())
    assert src.name == "bluesky"
    assert isinstance(src, EngagementSource)
    assert {MetricKind.LIKES, MetricKind.REPOSTS, MetricKind.REPLIES,
            MetricKind.QUOTES} <= src.supported_metrics


def test_bluesky_account_maps_profile_counts():
    client = FakeBskyClient()
    src = BlueskyEngagementSource("gnome.bsky.social", "pw", client=client)
    stats = src.account("gnome.bsky.social")
    assert client.logged_in == ("gnome.bsky.social", "pw")  # lazy login happened
    assert client.profile_actor == "gnome.bsky.social"
    assert isinstance(stats, AccountStats)
    assert (stats.followers, stats.follows, stats.posts) == (120, 80, 42)


def test_bluesky_engagement_maps_counts_into_bag():
    src = BlueskyEngagementSource("h", "p", client=FakeBskyClient())
    [e] = src.engagement(["at://1"])
    assert isinstance(e, PostEngagement)
    assert e.uri == "at://1"
    assert e.platform == "bluesky"
    assert e.metrics == {
        MetricKind.LIKES: 1, MetricKind.REPOSTS: 2,
        MetricKind.REPLIES: 3, MetricKind.QUOTES: 4,
    }


def test_bluesky_engagement_chunks_over_25_uris():
    client = FakeBskyClient()
    src = BlueskyEngagementSource("h", "p", client=client)
    out = src.engagement([f"at://{i}" for i in range(30)])
    assert len(out) == 30
    assert [len(c) for c in client.get_posts_calls] == [25, 5]  # batched at the API cap


def test_bluesky_engagement_empty_uris_makes_no_calls():
    client = FakeBskyClient()
    assert BlueskyEngagementSource("h", "p", client=client).engagement([]) == []
    assert client.get_posts_calls == []


# ── NullEngagementSource ──

def test_null_source_no_network_no_metrics():
    src = NullEngagementSource("bluesky")
    assert isinstance(src, EngagementSource)
    assert src.supported_metrics == frozenset()
    stats = src.account("h")
    assert (stats.followers, stats.follows, stats.posts) == (0, 0, 0)
    assert src.engagement(["at://1"]) == []


# ── make_engagement_source (live gate) ──

def test_factory_dryrun_returns_null(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    src = make_engagement_source("bluesky")
    assert isinstance(src, NullEngagementSource)
    assert src.name == "bluesky"


def test_factory_live_returns_bluesky(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "pw")
    monkeypatch.setenv("BLUESKY_HANDLE", "h.bsky.social")
    assert isinstance(make_engagement_source("bluesky"), BlueskyEngagementSource)


def test_factory_live_without_password_raises(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "")
    with pytest.raises(RuntimeError):
        make_engagement_source("bluesky")


def test_factory_unknown_platform_raises(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    with pytest.raises(ValueError):
        make_engagement_source("myspace")
