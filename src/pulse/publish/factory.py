"""make_publisher — the live gate.

Returns a real platform publisher only when PULSE_MODE=live (and credentials exist); otherwise a
DryRunPublisher that just logs. This is what keeps the pipeline from posting until deliberately
switched to live.
"""

from __future__ import annotations

from pulse import channels, config
from pulse.publish.base import Publisher
from pulse.publish.bluesky import BlueskyPublisher
from pulse.publish.dryrun import DryRunPublisher
from pulse.publish.mastodon import MastodonPublisher


def make_publisher(channel: dict) -> Publisher:
    platform = channels.validate_channel(channel)["platform"]

    if config.pulse_mode() != "live":
        return DryRunPublisher(platform, max_length=channels.max_length_for(channel))

    if platform == "bluesky":
        handle = channel.get("handle") or config.bluesky_handle()
        if not config.bluesky_app_password():
            raise RuntimeError("BLUESKY_APP_PASSWORD not set — cannot publish live to Bluesky.")
        return BlueskyPublisher(handle, config.bluesky_app_password())

    if platform == "mastodon":
        if not config.mastodon_access_token():
            raise RuntimeError("MASTODON_ACCESS_TOKEN not set — cannot publish live to Mastodon.")
        return MastodonPublisher(channel["instance"], config.mastodon_access_token(),
                                 max_length=channels.max_length_for(channel))

    raise ValueError(f"no publisher for platform: {platform!r}")  # pragma: no cover
