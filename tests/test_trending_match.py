"""Chunk 1 (revised): trend->market matching uses per-trend token co-occurrence.

A market matches a trend only if it contains ALL of that trend's significant tokens — so "World Cup"
needs both "world" AND "cup", not either (which matched ~6000 markets). Single proper-noun trends
still match on their one token.
"""

from __future__ import annotations

import datetime as dt

import pytest

from pulse.venue.trending import (
    Trend,
    market_matches,
    select_trending_markets,
    trend_keyword_groups,
)

NOW = dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.timezone.utc)


# ── trend_keyword_groups (one token-set per trend) ──
def test_group_keeps_multiword_tokens_together():
    assert trend_keyword_groups([Trend("Paraguay vs Germany")]) == [{"paraguay", "germany"}]


def test_group_strips_hashtag_and_punct():
    assert trend_keyword_groups([Trend("#Bitcoin")]) == [{"bitcoin"}]


def test_group_drops_stopwords():
    assert trend_keyword_groups([Trend("The Archers")]) == [{"archers"}]


def test_one_group_per_trend():
    assert trend_keyword_groups([Trend("Ken Paxton"), Trend("World Cup")]) == [
        {"ken", "paxton"}, {"world", "cup"}]


def test_empty_group_dropped():
    assert trend_keyword_groups([Trend("Dr. Oz")]) == []  # both tokens <3 chars


# ── market_matches (groups; ALL tokens of some group must be present) ──
def test_single_token_group_matches():
    assert market_matches("Will Germany win the World Cup?", [{"germany"}]) is True


def test_multi_token_group_requires_all_tokens():
    assert market_matches("Germany beat Paraguay", [{"paraguay", "germany"}]) is True
    assert market_matches("Will Germany win?", [{"paraguay", "germany"}]) is False  # paraguay absent


def test_common_token_alone_does_not_match():
    # "World Cup" trend must NOT match a market that only has "world"
    assert market_matches("World peace treaty odds", [{"world", "cup"}]) is False


def test_match_is_case_insensitive():
    assert market_matches("GERMANY advances", [{"germany"}]) is True


def test_match_is_word_level_not_substring():
    assert market_matches("Germany", [{"man"}]) is False


# ── select_trending_markets ──
def _market(title, *, status="active", vol=200, price=0.42, ticker="T1"):
    # volume_24h drives the floor; volume drives Snapshot.volume (the cap's ranking key)
    return {"ticker": ticker, "title": title, "status": status,
            "volume_24h": vol, "volume": vol, "last_price_dollars": price}


def _event(title, markets, *, category="Sports"):
    return {"category": category, "title": title, "event_ticker": "E1", "markets": markets}


def _select(events, groups, *, exclude=("Agriculture",), min_vol=100):
    return select_trending_markets(events, groups, NOW,
                                   exclude_categories=exclude, min_volume_24h=min_vol)


def test_selects_matching_market():
    snaps = _select([_event("Germany WC", [_market("Germany to win")])], [{"germany"}])
    assert len(snaps) == 1 and snaps[0].market_id == "T1" and snaps[0].venue == "kalshi"


def test_multiword_trend_does_not_over_match():
    # event has "world" but not "cup" -> the {"world","cup"} trend must not select it
    snaps = _select([_event("World peace summit", [_market("Treaty signed")])], [{"world", "cup"}])
    assert snaps == []


def test_matches_on_event_title_too():
    snaps = _select([_event("Germany World Cup run", [_market("Yes")])], [{"germany"}])
    assert len(snaps) == 1


def test_excludes_agriculture_food_category():
    ev = _event("Germany corn harvest", [_market("Germany corn")], category="Agriculture")
    assert _select([ev], [{"germany"}]) == []


def test_drops_below_volume_floor():
    assert _select([_event("Germany WC", [_market("Germany to win", vol=10)])], [{"germany"}]) == []


def test_skips_inactive_markets():
    assert _select([_event("Germany WC", [_market("x", status="closed")])], [{"germany"}]) == []


def test_no_groups_yields_nothing():
    assert _select([_event("Germany WC", [_market("Germany to win")])], []) == []


def test_caps_to_top_n_by_volume():
    ev = _event("Germany WC", [
        _market("Germany A", ticker="LO", vol=100),
        _market("Germany B", ticker="HI", vol=900),
        _market("Germany C", ticker="MID", vol=500),
    ])
    snaps = select_trending_markets([ev], [{"germany"}], NOW, exclude_categories=(),
                                    min_volume_24h=50, max_markets=2)
    assert {s.market_id for s in snaps} == {"HI", "MID"}  # top 2 by volume, drops the 100-vol one
