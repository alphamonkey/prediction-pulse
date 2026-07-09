"""Tests for ClaudeWriter — mock the Anthropic SDK at its boundary."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pulse import config
from pulse.models import Event, ValueKind
from pulse.persona import Persona
from pulse.writer.base import Draft, Writer
from pulse.writer.claude import ClaudeWriter

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)
_PERSONA = Persona(name="example", voice="You are a witty markets bot.")


def _event(headline="KXPRES: odds 45% -> 55% (+10pts)"):
    return Event(
        rule="odds_swing", venue="kalshi", market_id="KXPRES", ts=_T,
        value_kind=ValueKind.PROBABILITY, from_value=0.45, to_value=0.55,
        magnitude=0.10, direction="up", headline=headline,
        dedup_key="odds_swing:kalshi:KXPRES:2026-06-24",
    )


class FakeMessages:
    def __init__(self, text="Dem odds just popped to 55%. Not advice."):
        self.calls = []
        self._text = text

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self._text)],
            usage=SimpleNamespace(
                input_tokens=120, output_tokens=25,
                cache_read_input_tokens=0, cache_creation_input_tokens=0,
            ),
        )


class FakeClient:
    def __init__(self, text="Dem odds just popped to 55%. Not advice."):
        self.messages = FakeMessages(text)


def test_claude_writer_is_a_writer():
    w = ClaudeWriter(client=FakeClient())
    assert w.name == "claude"
    assert isinstance(w, Writer)


def test_writes_draft_from_model_text():
    client = FakeClient(text="  Dem odds popped to 55%. Not advice.  ")
    draft = ClaudeWriter(client=client).write(_event(), _PERSONA)
    assert isinstance(draft, Draft)
    assert draft.text == "Dem odds popped to 55%. Not advice."  # trimmed
    assert draft.event_dedup_key == _event().dedup_key
    assert draft.persona == "example"


def test_persona_voice_is_cached_system_event_in_user_message():
    client = FakeClient()
    ClaudeWriter(client=client).write(_event(headline="KXPRES jumped"), _PERSONA)
    kw = client.messages.calls[0]
    # persona voice is the system prefix, with cache_control for when it grows past the min
    assert kw["system"][0]["text"] == _PERSONA.voice
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["model"] == config.WRITER_MODEL
    assert kw["max_tokens"] == config.WRITER_MAX_TOKENS
    # volatile event facts live in the USER message (caching hygiene), not the system prompt
    user = kw["messages"][0]["content"]
    assert "KXPRES jumped" in user
    assert "KXPRES jumped" not in kw["system"][0]["text"]


def _generated_event():
    return Event(
        rule="generated", venue="generator", market_id="bean-history", ts=_T,
        value_kind=None, from_value=None, to_value=None, magnitude=1.0, direction=None,
        headline="bean history", dedup_key="generated:bean-history:2026-06-24T12:00",
        context={"source_kind": "generated"},
    )


def test_generated_event_renders_without_market_shape():
    client = FakeClient()
    ClaudeWriter(client=client).write(_generated_event(), _PERSONA)
    user = client.messages.calls[0]["messages"][0]["content"]
    assert "bean history" in user
    # No market residue for non-market events: no Market line, no venue, no % move.
    assert "Market:" not in user
    assert "generator" not in user
    assert "Moved" not in user


def test_length_enforced():
    draft = ClaudeWriter(client=FakeClient(text="z" * 400)).write(_event(), _PERSONA)
    assert len(draft.text) <= 300


def test_usage_is_tracked():
    w = ClaudeWriter(client=FakeClient())
    w.write(_event(), _PERSONA)
    w.write(_event(), _PERSONA)
    assert w.usage.calls == 2
    assert w.usage.input_tokens == 240
    assert w.usage.output_tokens == 50
    assert w.usage.total_cost > 0


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    with pytest.raises(RuntimeError):
        ClaudeWriter()  # no injected client, no key
