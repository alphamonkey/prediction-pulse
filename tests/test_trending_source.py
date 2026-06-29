"""Chunk 3: BlueskyTrendSource — trends + Kalshi events -> matched snapshots."""

from __future__ import annotations

import datetime as dt

import pytest

from pulse.venue.base import SnapshotSource
from pulse.venue.trending import BlueskyTrendSource, Trend

NOW = dt.datetime(2026, 7, 6, 12, 0, tzinfo=dt.timezone.utc)


class FakeTrendClient:
    def __init__(self, trends):
        self._trends = trends
        self.limit = None

    def get_trends(self, *, limit):
        self.limit = limit
        return self._trends


class FakeKalshi:
    def __init__(self, events):
        self._events = events
        self.called = False

    def iter_open_events(self, **kw):
        self.called = True
        return iter(self._events)


def _market(title, *, ticker="T1", price=0.42, vol=200, status="active"):
    return {"ticker": ticker, "title": title, "status": status,
            "volume_24h": vol, "last_price_dollars": price}


def _event(title, markets, *, category="Sports"):
    return {"category": category, "title": title, "event_ticker": "E1", "markets": markets}


def _source(trends, events, **kw):
    tc, kc = FakeTrendClient(trends), FakeKalshi(events)
    src = BlueskyTrendSource(tc, kc, limit=kw.get("limit", 25),
                             min_volume_24h=kw.get("min_vol", 100),
                             exclude_categories=kw.get("exclude", ("Agriculture",)))
    return src, tc, kc


def test_is_a_snapshotsource_for_kalshi():
    src, _, _ = _source([], [])
    assert isinstance(src, SnapshotSource)
    assert src.venue == "kalshi"


def test_snapshots_only_trend_matched_markets():
    events = [
        _event("Germany World Cup", [_market("Germany to win", ticker="WIN")], category="Sports"),
        _event("Fed June decision", [_market("Rate hike odds", ticker="FED")], category="Economics"),
    ]
    src, _, kc = _source([Trend("Germany")], events)
    snaps = src.fetch_snapshots(NOW)
    assert [s.market_id for s in snaps] == ["WIN"]  # the Fed event matches no trend keyword
    assert kc.called is True


def test_no_trends_yields_no_snapshots():
    src, _, kc = _source([], [_event("Germany WC", [_market("Germany to win")])])
    assert src.fetch_snapshots(NOW) == []


def test_passes_limit_to_trend_client():
    src, tc, _ = _source([], [], limit=12)
    src.fetch_snapshots(NOW)
    assert tc.limit == 12
