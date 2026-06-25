"""Deterministic event selection — the token-budget lever.

The detector emits far more events than we'd ever post. This ranks them so only the most
newsworthy few reach the (paid) writer. Pure and deterministic.

Score = rule weight (dominant) × a bounded magnitude factor × a gentle log-volume factor. Magnitude
is bounded so cross-rule magnitudes (probability points vs spike ratios vs volumes) stay comparable
and rule weight stays the primary signal; volume only breaks ties.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pulse.config import RULE_WEIGHTS
from pulse.models import Event


def _score(event: Event) -> float:
    weight = RULE_WEIGHTS.get(event.rule, 0.0)
    mag_factor = 1.0 + min(abs(event.magnitude), 1.0)
    vol = 0.0
    if event.meta is not None and isinstance(event.meta.extra, dict):
        vol = float(event.meta.extra.get("volume_24h") or 0.0)
    vol_factor = 1.0 + math.log10(1.0 + max(vol, 0.0)) / 10.0
    return weight * mag_factor * vol_factor


def select_events(events: Sequence[Event], *, limit: int) -> list[Event]:
    """Return the top `limit` events by newsworthiness, highest first (deterministic)."""
    ranked = sorted(events, key=lambda e: (_score(e), e.dedup_key), reverse=True)
    return ranked[:limit]
