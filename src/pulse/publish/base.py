"""The publisher seam: post a Draft to one channel, behind a swappable interface.

Platform-specific publishers (Bluesky now; X/Threads/Mastodon later) implement `Publisher`. A
persona's `channels` drive which publishers run. `make_publisher` (factory.py) returns a real
publisher only in live mode — otherwise a DryRunPublisher — so nothing posts until deliberately
switched.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pulse.persona import Persona
from pulse.writer.base import Draft


@dataclass
class PostResult:
    """Outcome of attempting to publish one draft to one channel."""

    channel: str
    posted: bool  # True only if a real post happened (dryrun -> False)
    uri: str | None = None  # platform post id (at:// for Bluesky)
    cid: str | None = None
    text: str = ""


@runtime_checkable
class Publisher(Protocol):
    name: str  # the channel/platform, e.g. "bluesky"
    max_length: int  # the channel's hard post limit — a capability, like Engager.supported_actions

    def publish(self, draft: Draft, persona: Persona) -> PostResult:
        ...
