"""NullTargetSource — finds nothing, safely.

What a known platform with no target source of its own gets. Without it, make_target_source would
raise for such a platform, and since EngageJob loops a persona's channels, adding that channel to a
live persona would take its whole engage job down on the first cycle.
"""

from __future__ import annotations

import logging

from pulse.engage.base import Target

log = logging.getLogger("pulse")


class NullTargetSource:
    def __init__(self, platform: str) -> None:
        self.name = f"null:{platform}"

    def find_targets(self, *, limit: int) -> list[Target]:
        log.info("engage: no target source for %s — nothing to engage", self.name)
        return []
