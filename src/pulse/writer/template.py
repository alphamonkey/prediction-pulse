"""TemplateWriter — a deterministic, zero-token writer.

Builds a post directly from the Event's already-human-readable `headline`. It's the dryrun/test
fallback (no API key needed) and the baseline the ClaudeWriter improves on. For generated
(seed) events the headline is the raw topic seed, so dryrun output reads as the seed itself —
acceptable, since generator personas need a live writer to invent anything.
"""

from __future__ import annotations

from pulse.models import Event
from pulse.persona import Persona
from pulse.writer.base import Draft, enforce_length


class TemplateWriter:
    name = "template"

    def write(self, event: Event, persona: Persona, context: dict | None = None) -> Draft:
        return Draft(
            event_dedup_key=event.dedup_key,
            persona=persona.name,
            text=enforce_length(event.headline, persona.draft_max_length()),
        )
