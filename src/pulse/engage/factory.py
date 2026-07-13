"""make_engager — the live gate (a direct mirror of make_publisher).

Returns a real engager only when PULSE_MODE=live (and credentials exist); otherwise a DryRunEngager
that just logs. This is what keeps engagement from touching the live account until deliberately
switched on.
"""

from __future__ import annotations

from pulse import channels, config
from pulse.engage.base import Engager, TargetSource
from pulse.engage.bluesky import BlueskySignalEngager
from pulse.engage.dryrun import DryRunEngager
from pulse.engage.search import TopicalSearchSource


def make_target_source(channel: dict, policy) -> TargetSource:
    """Build the inbound target source for a channel. Read-only, so NOT live-gated — dryrun still
    finds targets so you can preview what it *would* engage."""
    platform = channels.validate_channel(channel)["platform"]
    if platform == "bluesky":
        return TopicalSearchSource(channels.handle_for(channel), config.bluesky_app_password(),
                                   queries=policy.queries)
    raise ValueError(f"no engage target source for platform: {platform!r}")


def make_engager(channel: dict) -> Engager:
    platform = channels.validate_channel(channel)["platform"]

    if config.pulse_mode() != "live":
        return DryRunEngager(platform)

    if platform == "bluesky":
        if not config.bluesky_app_password():
            raise RuntimeError("BLUESKY_APP_PASSWORD not set — cannot engage live on Bluesky.")
        return BlueskySignalEngager(channels.handle_for(channel), config.bluesky_app_password())

    raise ValueError(f"unknown engage platform: {platform!r}")  # pragma: no cover
