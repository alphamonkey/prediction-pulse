"""Tests for the normalized data models — the seam the detector is written against."""

from datetime import datetime, timezone

import pytest

from pulse.models import Event, MarketMeta, Snapshot, ValueKind

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def test_value_kind_values():
    assert ValueKind.PROBABILITY.value == "PROBABILITY"
    assert ValueKind.PRICE.value == "PRICE"
    # str-mixin: compares/serializes as its string value
    assert ValueKind.PROBABILITY == "PROBABILITY"


def test_snapshot_is_frozen():
    snap = Snapshot(
        venue="kalshi",
        market_id="KXTEST",
        ts=_T,
        value=0.5,
        value_kind=ValueKind.PROBABILITY,
    )
    assert snap.volume == 0.0  # default
    assert snap.meta is None  # default
    with pytest.raises(Exception):
        snap.value = 0.6  # type: ignore[misc]


def test_market_meta_defaults():
    meta = MarketMeta()
    assert meta.title is None
    assert meta.status is None
    assert meta.resolution_date is None
    assert meta.category is None
    assert meta.extra == {}


def test_market_meta_extra_is_independent():
    a = MarketMeta()
    b = MarketMeta()
    a.extra["x"] = 1
    assert b.extra == {}  # no shared mutable default


def test_event_defaults():
    ev = Event(
        rule="odds_swing",
        venue="kalshi",
        market_id="KXTEST",
        ts=_T,
        value_kind=ValueKind.PROBABILITY,
        from_value=0.40,
        to_value=0.55,
        magnitude=0.15,
        direction="up",
        headline="KXTEST: odds 40% -> 55%",
        dedup_key="odds_swing:kalshi:KXTEST:2026-06-24",
    )
    assert ev.context == {}
    assert ev.meta is None
    with pytest.raises(Exception):
        ev.magnitude = 0.2  # type: ignore[misc]


def test_event_supports_non_market_shape():
    """Generated content has no market semantics: value_kind None, no numerics."""
    ev = Event(
        rule="generated",
        venue="generator",
        market_id="bean-history",
        ts=_T,
        value_kind=None,
        from_value=None,
        to_value=None,
        magnitude=1.0,
        direction=None,
        headline="Topic: bean history",
        dedup_key="generated:bean-history:2026-06-24T12",
        context={"source_kind": "generated"},
    )
    assert ev.value_kind is None
    assert ev.context["source_kind"] == "generated"


def test_event_context_is_independent():
    common = dict(
        rule="r", venue="v", market_id="m", ts=_T, value_kind=ValueKind.PROBABILITY,
        from_value=None, to_value=None, magnitude=0.0, direction=None,
        headline="h", dedup_key="k",
    )
    a = Event(**common)
    b = Event(**common)
    a.context["x"] = 1
    assert b.context == {}
