"""Tests for deterministic event selection (the token-budget lever)."""

from datetime import datetime, timezone

from pulse.models import Event, MarketMeta, ValueKind
from pulse.writer.select import select_events

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


def _event(rule, market_id, magnitude=0.2, volume_24h=1000.0):
    return Event(
        rule=rule, venue="kalshi", market_id=market_id, ts=_T,
        value_kind=ValueKind.PROBABILITY, from_value=0.4, to_value=0.6,
        magnitude=magnitude, direction="up", headline=f"{market_id} moved",
        dedup_key=f"{rule}:kalshi:{market_id}:2026-06-24",
        meta=MarketMeta(extra={"volume_24h": volume_24h}),
    )


def test_empty_input():
    assert select_events([], limit=5) == []


def test_caps_at_limit():
    events = [_event("odds_swing", f"M{i}") for i in range(10)]
    assert len(select_events(events, limit=3)) == 3


def test_higher_rule_weight_ranks_first():
    # same magnitude/volume — milestone (weight 3) should beat new_market (weight 1)
    new = _event("new_market", "NEW")
    milestone = _event("milestone", "MILE")
    out = select_events([new, milestone], limit=1)
    assert [e.market_id for e in out] == ["MILE"]


def test_higher_magnitude_ranks_first_within_rule():
    small = _event("odds_swing", "SMALL", magnitude=0.10)
    big = _event("odds_swing", "BIG", magnitude=0.40)
    out = select_events([small, big], limit=1)
    assert out[0].market_id == "BIG"


def test_higher_volume_breaks_ties():
    quiet = _event("odds_swing", "QUIET", volume_24h=100.0)
    loud = _event("odds_swing", "LOUD", volume_24h=50000.0)
    out = select_events([quiet, loud], limit=1)
    assert out[0].market_id == "LOUD"


def test_generated_rule_has_a_configured_weight():
    generated = Event(
        rule="generated", venue="generator", market_id="beans", ts=_T,
        value_kind=None, from_value=None, to_value=None, magnitude=1.0, direction=None,
        headline="beans", dedup_key="generated:beans:2026-06-24T12:00",
        context={"source_kind": "generated"},
    )
    unweighted = _event("mystery", "X")
    out = select_events([unweighted, generated], limit=1)
    assert out[0].rule == "generated"  # generated events must survive ranking


def test_unknown_rule_does_not_crash():
    # a rule with no configured weight still ranks (lowest), never errors
    out = select_events([_event("mystery", "X")], limit=5)
    assert [e.market_id for e in out] == ["X"]
