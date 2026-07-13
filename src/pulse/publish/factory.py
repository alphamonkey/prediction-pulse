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


def make_publisher(channel: dict) -> Publisher:
    platform = channels.validate_channel(channel)["platform"]

    if config.pulse_mode() != "live":
        return DryRunPublisher(platform, max_length=channels.max_length_for(channel))

    if platform == "bluesky":
        handle = channel.get("handle") or config.bluesky_handle()
        if not config.bluesky_app_password():
            raise RuntimeError("BLUESKY_APP_PASSWORD not set — cannot publish live to Bluesky.")
        return BlueskyPublisher(handle, config.bluesky_app_password())

    raise ValueError(f"unknown publish platform: {platform!r}")  # pragma: no cover
