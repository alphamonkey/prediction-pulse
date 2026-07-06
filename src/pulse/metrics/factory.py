"""make_engagement_source — the live gate for metrics collection.

Returns a real platform source only when PULSE_MODE=live (and credentials exist); otherwise a
NullEngagementSource that touches no network. Mirrors publish/factory.py. New platforms register in
`_KNOWN`.
"""

from __future__ import annotations

from pulse import config
from pulse.metrics.base import EngagementSource
from pulse.metrics.bluesky import BlueskyEngagementSource
from pulse.metrics.dryrun import NullEngagementSource

_KNOWN = {"bluesky"}


def make_engagement_source(platform: str) -> EngagementSource:
    if platform not in _KNOWN:
        raise ValueError(f"unknown engagement platform: {platform!r}")

    if config.pulse_mode() != "live":
        return NullEngagementSource(platform)

    if platform == "bluesky":
        if not config.bluesky_app_password():
            raise RuntimeError("BLUESKY_APP_PASSWORD not set — cannot collect engagement from Bluesky.")
        return BlueskyEngagementSource(config.bluesky_handle(), config.bluesky_app_password())

    raise ValueError(f"unknown engagement platform: {platform!r}")  # pragma: no cover
