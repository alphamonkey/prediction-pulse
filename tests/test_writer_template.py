"""Tests for the Writer seam (Draft + Protocol + length guard) and TemplateWriter."""

from datetime import datetime, timezone

from pulse.models import Event, ValueKind
from pulse.persona import Persona
from pulse.writer.base import Draft, Writer, enforce_bluesky_length
from pulse.writer.template import TemplateWriter

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
_PERSONA = Persona(name="example", voice="be punchy")


def _event(headline="KXPRES: odds 45% -> 55% (+10pts)"):
    return Event(
        rule="odds_swing", venue="kalshi", market_id="KXPRES", ts=_T,
        value_kind=ValueKind.PROBABILITY, from_value=0.45, to_value=0.55,
        magnitude=0.10, direction="up", headline=headline,
        dedup_key="odds_swing:kalshi:KXPRES:2026-06-24",
    )


def test_enforce_length_trims_to_limit():
    long = "x" * 400
    out = enforce_bluesky_length(long)
    assert len(out) <= 300


def test_enforce_length_leaves_short_text():
    assert enforce_bluesky_length("short") == "short"


def test_template_writer_is_a_writer():
    w = TemplateWriter()
    assert w.name == "template"
    assert isinstance(w, Writer)


def test_template_writer_drafts_from_headline():
    ev = _event()
    draft = TemplateWriter().write(ev, _PERSONA)
    assert isinstance(draft, Draft)
    assert ev.headline in draft.text
    assert draft.event_dedup_key == ev.dedup_key
    assert draft.persona == "example"
    assert draft.media == []


def test_template_writer_enforces_length():
    ev = _event(headline="y" * 400)
    draft = TemplateWriter().write(ev, _PERSONA)
    assert len(draft.text) <= 300
