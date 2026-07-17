"""make_engagement_source — the live gate for metrics collection.

Returns a real platform source only when PULSE_MODE=live (and credentials exist); otherwise a
NullEngagementSource that touches no network. Takes a channel dict, exactly like make_publisher and
make_engager — the three gates are the same shape on purpose.
"""

from __future__ import annotations

from pulse import channels, config
from pulse.metrics.base import EngagementSource
from pulse.metrics.bluesky import BlueskyEngagementSource
from pulse.metrics.dryrun import NullEngagementSource
from pulse.metrics.mastodon import MastodonEngagementSource


def make_engagement_source(channel: dict) -> EngagementSource:
    platform = channels.validate_channel(channel)["platform"]

    if config.pulse_mode() != "live":
        return NullEngagementSource(platform)

    if platform == "bluesky":
        if not config.bluesky_app_password():
            raise RuntimeError(
                "BLUESKY_APP_PASSWORD not set — cannot collect engagement from Bluesky.")
        return BlueskyEngagementSource(channels.handle_for(channel),
                                       config.bluesky_app_password())

    if platform == "mastodon":
        if not config.mastodon_access_token():
            raise RuntimeError(
                "MASTODON_ACCESS_TOKEN not set — cannot collect engagement from Mastodon.")
        return MastodonEngagementSource(channel["instance"], config.mastodon_access_token())

    raise ValueError(f"no engagement source for platform: {platform!r}")
