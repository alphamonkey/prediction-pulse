from datetime import datetime, timezone

from pulse.models import ValueKind
from pulse.venue.kalshi import market_to_snapshot

_NOW = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _raw(**over):
    base = {
        "ticker": "KXPRES-2028-DEM",
        "title": "Will a Democrat win in 2028?",
        "status": "active",
        "close_time": "2028-11-07T00:00:00Z",
        "last_price": 62,            # cents
        "yes_bid": 60,
        "yes_ask": 64,
        "volume": 12345,
        "volume_24h": 999,
        "event_ticker": "KXPRES-2028",
        "series_ticker": "KXPRES",
    }
    base.update(over)
    return base


def test_uses_last_price_in_cents():
    snap = market_to_snapshot(_raw(), category="Politics", now=_NOW)
    assert snap is not None
    assert snap.venue == "kalshi"
    assert snap.market_id == "KXPRES-2028-DEM"
    assert abs(snap.value - 0.62) < 1e-9
    assert snap.value_kind is ValueKind.PROBABILITY
    assert snap.volume == 12345
    assert snap.ts == _NOW


def test_prefers_dollars_field_over_cents():
    snap = market_to_snapshot(_raw(last_price_dollars=0.41), category="Politics", now=_NOW)
    assert abs(snap.value - 0.41) < 1e-9


def test_falls_back_to_mid_when_no_last_price():
    snap = market_to_snapshot(_raw(last_price=0), category="Politics", now=_NOW)
    assert abs(snap.value - 0.62) < 1e-9  # (60 + 64) / 2 / 100


def test_skips_when_unpriceable():
    raw = _raw(last_price=0, yes_bid=0, yes_ask=0)
    assert market_to_snapshot(raw, category="Politics", now=_NOW) is None


def test_skips_when_no_ticker():
    raw = _raw()
    del raw["ticker"]
    assert market_to_snapshot(raw, category="Politics", now=_NOW) is None


def test_maps_meta_fields():
    snap = market_to_snapshot(_raw(), category="Politics", now=_NOW)
    assert snap.meta.title == "Will a Democrat win in 2028?"
    assert snap.meta.status == "active"
    assert snap.meta.resolution_date == "2028-11-07T00:00:00Z"
    assert snap.meta.category == "Politics"
    assert snap.meta.extra["event_ticker"] == "KXPRES-2028"
    assert snap.meta.extra["series_ticker"] == "KXPRES"
    assert snap.meta.extra["volume_24h"] == 999
