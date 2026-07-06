"""ClaudeWriter — a single cheap Haiku call that phrases an Event in a persona's voice.

Mirrors kalshi-bot's ClaudeAgent: the persona voice is the (cacheable) system prefix; the volatile,
already-verified event facts go in the user message. No effort/thinking (Haiku rejects effort);
low max_tokens. Usage + cost are tracked. The model is given ONLY verified numbers, so it cannot
fabricate.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from pulse import config
from pulse.models import Event
from pulse.persona import Persona
from pulse.writer.base import Draft, enforce_bluesky_length


@dataclass
class WriterUsage:
    """Token + cost accounting across calls. Haiku 4.5: $1/M in, $5/M out, ~$0.10/M cache read."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_create_tokens: int = 0

    @property
    def total_cost(self) -> float:
        return (
            self.input_tokens * 1.0 / 1_000_000
            + self.output_tokens * 5.0 / 1_000_000
            + self.cache_read_tokens * 0.10 / 1_000_000
            + self.cache_create_tokens * 1.25 / 1_000_000
        )

    def record(self, usage) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_create_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0


def _render_event(event: Event) -> str:
    """Lay out the verified facts the writer may use — nothing else."""
    lines = [f"Headline: {event.headline}", f"Signal: {event.rule}"]
    if event.from_value is not None and event.to_value is not None:
        lines.append(f"Moved from {event.from_value:.0%} to {event.to_value:.0%}")
    if event.direction:
        lines.append(f"Direction: {event.direction}")
    lines.append(f"Market: {event.market_id} ({event.venue})")
    return "\n".join(lines)


class ClaudeWriter:
    name = "claude"

    def __init__(
        self,
        *,
        client: anthropic.Anthropic | None = None,
        model: str = config.WRITER_MODEL,
        max_tokens: int = config.WRITER_MAX_TOKENS,
    ) -> None:
        if client is None:
            if not config.anthropic_api_key():
                raise RuntimeError("ANTHROPIC_API_KEY not set — cannot use ClaudeWriter.")
            client = anthropic.Anthropic()
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self.usage = WriterUsage()

    def write(self, event: Event, persona: Persona, context: dict | None = None) -> Draft:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=[{
                "type": "text",
                "text": persona.voice,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": _render_event(event)}],
        )
        self.usage.record(response.usage)
        text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text")
        return Draft(
            event_dedup_key=event.dedup_key,
            persona=persona.name,
            text=enforce_bluesky_length(text),
            context=context or {},
        )
