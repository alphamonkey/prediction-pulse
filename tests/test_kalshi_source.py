from datetime import datetime, timezone

from pulse.venue.base import SnapshotSource
from pulse.venue.kalshi import KalshiSource

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, events):
        self._events = events

    def iter_open_events(self, *, limit=200):
        yield from self._events


def _market(ticker, **over):
    m = {"ticker": ticker, "status": "active", "last_price": 50,
         "volume": 100, "volume_24h": 5000}
    m.update(over)
    return m


def _event(category, markets, event_ticker="E1"):
    return {"event_ticker": event_ticker, "category": category, "markets": markets}


def test_keeps_only_allowlisted_categories():
    events = [
        _event("Politics", [_market("A")]),
        _event("Weather", [_market("B")]),
    ]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=0)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"A"}


def test_applies_volume_floor():
    events = [_event("Politics", [_market("A", volume_24h=10), _market("B", volume_24h=9000)])]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=1000)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"B"}


def test_skips_non_active_and_unpriceable():
    events = [_event("Politics", [
        _market("A", status="finalized"),
        _market("B", last_price=0, yes_bid=0, yes_ask=0),
        _market("C"),
    ])]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=0)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"C"}


def test_is_a_snapshot_source_with_venue():
    src = KalshiSource(FakeClient([]))
    assert src.venue == "kalshi"
    assert isinstance(src, SnapshotSource)


def test_volume_floor_uses_volume_24h_fp():
    """Live Kalshi API uses volume_24h_fp — floor must filter on that field."""
    events = [_event("Politics", [
        _market("KEEP", volume_24h_fp=5000),
        _market("DROP", volume_24h_fp=10),
    ])]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=1000)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"KEEP"}


def test_volume_floor_legacy_volume_24h_still_works():
    """volume_24h (legacy) fallback must keep existing tests passing."""
    events = [_event("Politics", [
        _market("KEEP", volume_24h=8000),
        _market("DROP", volume_24h=5),
    ])]
    src = KalshiSource(FakeClient(events), categories={"Politics"}, min_volume_24h=1000)
    ids = {s.market_id for s in src.fetch_snapshots(_NOW)}
    assert ids == {"KEEP"}
