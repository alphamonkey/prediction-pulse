"""DryRunEngager — logs what it would do, touches no network, takes no action.

The safety default outside live mode: stands in for every channel so no real likes/reposts/follows
happen. Returns `performed=False`, so the orchestrator records nothing — flipping to live engages
fresh.
"""

from __future__ import annotations

import logging

from pulse.engage.base import EngageResult, SignalKind, Target

log = logging.getLogger("pulse")


class DryRunEngager:
    supported_actions = frozenset({SignalKind.LIKE, SignalKind.REPOST, SignalKind.FOLLOW})

    def __init__(self, channel: str) -> None:
        self.name = channel

    def engage(self, target: Target, action: SignalKind) -> EngageResult:
        log.info("would %s [%s]: %s", action.value, self.name, target.uri or target.author_handle)
        return EngageResult(
            action=action, target_uri=target.uri, target_did=target.author_did, performed=False
        )
