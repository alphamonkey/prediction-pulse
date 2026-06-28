"""make_engager — the live gate (a direct mirror of make_publisher).

Returns a real engager only when PULSE_MODE=live (and credentials exist); otherwise a DryRunEngager
that just logs. This is what keeps engagement from touching the live account until deliberately
switched on.
"""

from __future__ import annotations

from pulse import config
from pulse.engage.base import Engager, TargetSource
from pulse.engage.bluesky import BlueskySignalEngager
from pulse.engage.dryrun import DryRunEngager
from pulse.engage.search import TopicalSearchSource

_KNOWN = {"bluesky"}


def make_target_source(channel: dict, policy) -> TargetSource:
    """Build the inbound target source for a channel. Read-only, so NOT live-gated — dryrun still
    finds targets so you can preview what it *would* engage. (Needs Bluesky creds to search.)"""
    platform = channel.get("platform")
    if platform == "bluesky":
        handle = channel.get("handle") or config.BLUESKY_HANDLE
        return TopicalSearchSource(handle, config.BLUESKY_APP_PASSWORD, queries=policy.queries)
    raise ValueError(f"unknown engage platform: {platform!r}")


def make_engager(channel: dict) -> Engager:
    platform = channel.get("platform")
    if platform not in _KNOWN:
        raise ValueError(f"unknown engage platform: {platform!r}")

    if config.PULSE_MODE != "live":
        return DryRunEngager(platform)

    if platform == "bluesky":
        handle = channel.get("handle") or config.BLUESKY_HANDLE
        if not config.BLUESKY_APP_PASSWORD:
            raise RuntimeError("BLUESKY_APP_PASSWORD not set — cannot engage live on Bluesky.")
        return BlueskySignalEngager(handle, config.BLUESKY_APP_PASSWORD)

    raise ValueError(f"unknown engage platform: {platform!r}")  # pragma: no cover
