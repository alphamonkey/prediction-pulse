"""Chunk 1: engagement vocabulary + the pure relevance/safety filter."""

from __future__ import annotations

import pytest

from pulse.engage.base import SignalKind, Target
from pulse.engage.filter import filter_targets, passes_filter


def _t(uri: str, text: str, *, did: str = "did:plc:a", handle: str = "a.bsky.social") -> Target:
    return Target(
        uri=uri, cid="cid", author_did=did, author_handle=handle, text=text, source="topical-search"
    )


def test_signalkind_v1_values():
    assert SignalKind.LIKE.value == "like"
    assert SignalKind.REPOST.value == "repost"
    assert SignalKind.FOLLOW.value == "follow"


def test_signalkind_reserves_reply_and_quote_for_later():
    # The seam carries them so reactive actions slot in without a vocabulary change.
    assert SignalKind.REPLY.value == "reply"
    assert SignalKind.QUOTE.value == "quote"


def test_target_holds_engagement_metadata():
    t = _t("at://x/1", "Kalshi odds are wild today")
    assert t.uri == "at://x/1"
    assert t.author_handle == "a.bsky.social"
    assert t.source == "topical-search"


def test_passes_filter_keeps_relevant_and_safe():
    t = _t("at://x/1", "Big move in the Kalshi prediction market today")
    assert passes_filter(t, allow=["kalshi", "prediction market"], deny=["election", "abortion"])


def test_passes_filter_drops_off_topic_when_allowlist_set():
    t = _t("at://x/1", "My cat knocked over a plant")
    assert not passes_filter(t, allow=["kalshi", "prediction market"], deny=[])


def test_passes_filter_rejects_denylisted_even_if_relevant():
    t = _t("at://x/1", "Kalshi market on the 2028 election is heating up")
    assert not passes_filter(t, allow=["kalshi"], deny=["election"])


def test_passes_filter_is_case_insensitive():
    t = _t("at://x/1", "KALSHI is popping off")
    assert passes_filter(t, allow=["kalshi"], deny=["ELECTION"])
    t2 = _t("at://x/2", "thoughts on the ELECTION")
    assert not passes_filter(t2, allow=[], deny=["election"])


def test_passes_filter_empty_allowlist_keeps_anything_safe():
    t = _t("at://x/1", "random but harmless post")
    assert passes_filter(t, allow=[], deny=["election"])


def test_filter_targets_returns_only_passing():
    ts = [
        _t("at://x/1", "Kalshi prediction market move"),
        _t("at://x/2", "unrelated lunch photo"),
        _t("at://x/3", "Kalshi market on the election"),
    ]
    out = filter_targets(ts, allow=["kalshi"], deny=["election"])
    assert [t.uri for t in out] == ["at://x/1"]


def test_filter_targets_dedupes_by_uri_keeping_first():
    ts = [
        _t("at://x/1", "Kalshi move one"),
        _t("at://x/1", "Kalshi move duplicate"),
    ]
    out = filter_targets(ts, allow=["kalshi"], deny=[])
    assert len(out) == 1
    assert out[0].text == "Kalshi move one"
