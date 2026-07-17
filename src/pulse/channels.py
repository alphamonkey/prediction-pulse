"""Channel registry: what a platform is capable of, and what its [[channels]] block must declare.

Pure data + validation — this module never constructs an adapter, and that is the point. The writer
must know how long a draft may be before it writes one, and `load_persona` must reject a malformed
[[channels]] block at load time; neither should need credentials, a network client, or a live
Publisher to find out. The three factories (publish/engage/metrics) build the adapters; this says
which platforms exist and what they can do.

Mirrors venue/registry.py: one spec per entry, each owning the validation of its own keys.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from pulse import config
from pulse.engage.base import SignalKind


@dataclass(frozen=True)
class ChannelSpec:
    """A platform's capabilities, declared without instantiating anything that talks to it."""

    platform: str
    max_length: int
    actions: frozenset[SignalKind]         # what an Engager on this platform can do
    required: tuple[str, ...] = ()         # channel-dict keys that MUST be present
    optional: tuple[str, ...] = ()         # ... and those that may be
    handle_default: Callable[[], str] = field(default=lambda: "")

    @property
    def allowed(self) -> tuple[str, ...]:
        return ("platform", *self.required, *self.optional)


_SIGNALS = frozenset({SignalKind.LIKE, SignalKind.REPOST, SignalKind.FOLLOW})

_SPECS: dict[str, ChannelSpec] = {
    "bluesky": ChannelSpec(
        platform="bluesky",
        max_length=config.BLUESKY_MAX_GRAPHEMES,
        actions=_SIGNALS,
        optional=("handle",),
        handle_default=config.bluesky_handle,
    ),
    # Instance-agnostic by construction: the base URL is required config, never a default. The
    # token identifies the account (verify_credentials), so `handle` is cosmetic — it exists so
    # the engager can skip the persona's own posts.
    "mastodon": ChannelSpec(
        platform="mastodon",
        max_length=config.MASTODON_MAX_CHARS,
        actions=_SIGNALS,
        required=("instance",),
        optional=("handle", "max_length"),
    ),
}


def known_platforms() -> tuple[str, ...]:
    return tuple(sorted(_SPECS))


def channel_spec(platform: str) -> ChannelSpec:
    try:
        return _SPECS[platform]
    except KeyError:
        known = ", ".join(known_platforms())
        raise ValueError(f"unknown channel platform {platform!r} (known: {known})") from None


def validate_channel(channel: object) -> dict:
    """Check one [[channels]] block. Raises ValueError so an operator typo fails loudly at persona
    load, rather than three hours later when the publish cycle first reaches the factory."""
    if not isinstance(channel, dict):
        raise ValueError(f"[[channels]] entries must be tables, got {type(channel).__name__}")
    platform = channel.get("platform")
    if not platform:
        raise ValueError("[[channels]] entry is missing `platform`")

    spec = channel_spec(str(platform))
    missing = [key for key in spec.required if key not in channel]
    if missing:
        raise ValueError(
            f"channel {spec.platform!r} is missing required key(s): {', '.join(missing)}")
    unknown = set(channel) - set(spec.allowed)
    if unknown:
        raise ValueError(
            f"channel {spec.platform!r} has unknown key(s): {', '.join(sorted(unknown))}")
    return channel


def validate_channels(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        raise ValueError(f"`channels` must be a list of tables, got {type(raw).__name__}")
    return [validate_channel(channel) for channel in raw]


def max_length_for(channel: dict) -> int:
    """This channel's hard post limit — the platform default, unless the channel overrides it
    (Mastodon instances configure their own)."""
    spec = channel_spec(str(channel.get("platform")))
    return int(channel.get("max_length", spec.max_length))


def draft_max_length(channels: list[dict]) -> int:
    """How long one canonical draft may be for a persona publishing to `channels`.

    The draft is fanned out to every channel, so it must fit the SMALLEST of them — write to 500
    for Mastodon and the Bluesky publisher truncates it back to 300 with an ellipsis. A persona
    with no channels keeps the historical Bluesky limit.
    """
    if not channels:
        return config.BLUESKY_MAX_GRAPHEMES
    return min(max_length_for(channel) for channel in channels)


def handle_for(channel: dict) -> str:
    """The account this channel acts as: the channel's own handle, else the platform's credential
    default. Never another platform's identity — the bug this replaces fell back to BLUESKY_HANDLE
    for every platform, so a Mastodon channel would silently act as the Bluesky account.
    """
    spec = channel_spec(str(channel.get("platform")))
    return str(channel.get("handle") or spec.handle_default())
