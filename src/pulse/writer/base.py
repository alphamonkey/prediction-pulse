"""The writer seam: turn an Event into a post Draft in a Persona's voice.

A Writer is the swappable *mechanism* (template now, Claude now, tool/MCP later). `Draft` carries
optional `media`/`context` so richer future writers slot in without changing consumers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from pulse.models import Event, _now
from pulse.persona import Persona


@dataclass
class Draft:
    """A generated post awaiting review/publishing."""

    event_dedup_key: str
    persona: str
    text: str
    media: list = field(default_factory=list)  # future: charts/images
    context: dict = field(default_factory=dict)  # future: tool/news context used
    created_at: datetime = field(default_factory=_now)


@runtime_checkable
class Writer(Protocol):
    name: str

    def write(self, event: Event, persona: Persona, context: dict | None = None) -> Draft:
        """Render one post draft for `event` in `persona`'s voice."""
        ...


def enforce_length(text: str, limit: int) -> str:
    """Safety net so a draft never exceeds a channel's limit. Trims with an ellipsis.

    `limit` is explicit because it belongs to the channel, not to this module: the writer passes
    the persona's tightest channel, each publisher passes its own.
    """
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
