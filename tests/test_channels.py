"""Tests for the channel registry: platform capabilities + [[channels]] validation.

The registry is pure data — it must answer "how long may a post be on this platform" and "is this
[[channels]] block well-formed" WITHOUT credentials, a network client, or a live adapter.
"""

import pytest

from pulse import channels, config
from pulse.engage.base import SignalKind
from pulse.engage.bluesky import BlueskySignalEngager

_BSKY = {"platform": "bluesky", "handle": "gnome.bsky.social"}
_MASTO = {"platform": "mastodon", "instance": "https://mastodon.social"}


def test_known_platforms():
    assert set(channels.known_platforms()) >= {"bluesky", "mastodon"}


def test_channel_spec_carries_the_platform_limit():
    assert channels.channel_spec("bluesky").max_length == config.BLUESKY_MAX_GRAPHEMES
    assert channels.channel_spec("mastodon").max_length == config.MASTODON_MAX_CHARS


def test_channel_spec_rejects_an_unknown_platform():
    with pytest.raises(ValueError, match="myspace"):
        channels.channel_spec("myspace")


# ── validation: an operator typo must fail at persona load, not three hours later at post time ──

def test_validate_accepts_the_live_channel_shapes():
    assert channels.validate_channel(_BSKY) == _BSKY
    assert channels.validate_channel(_MASTO) == _MASTO
    assert channels.validate_channel({"platform": "bluesky"}) == {"platform": "bluesky"}


def test_validate_rejects_a_bare_string():
    with pytest.raises(ValueError, match="table"):
        channels.validate_channel("bluesky")


def test_validate_rejects_a_missing_or_unknown_platform():
    with pytest.raises(ValueError, match="platform"):
        channels.validate_channel({"handle": "gnome.bsky.social"})
    with pytest.raises(ValueError, match="twiter"):
        channels.validate_channel({"platform": "twiter"})


def test_validate_rejects_mastodon_without_an_instance():
    """The adapter is instance-agnostic, so the instance MUST be declared — there is no default."""
    with pytest.raises(ValueError, match="instance"):
        channels.validate_channel({"platform": "mastodon"})


def test_validate_rejects_an_unknown_key():
    with pytest.raises(ValueError, match="handel"):
        channels.validate_channel({"platform": "bluesky", "handel": "typo"})


def test_validate_channels_maps_over_the_list():
    assert channels.validate_channels([_BSKY, _MASTO]) == [_BSKY, _MASTO]
    assert channels.validate_channels([]) == []


# ── length: a capability of the platform, overridable per channel ──

def test_max_length_for_uses_the_platform_default():
    assert channels.max_length_for(_BSKY) == 300
    assert channels.max_length_for(_MASTO) == 500


def test_max_length_for_honors_a_per_channel_override():
    """Mastodon instances configure their own limit, so the channel may say so."""
    assert channels.max_length_for({**_MASTO, "max_length": 480}) == 480


def test_draft_max_length_is_the_minimum_across_channels():
    """One canonical draft is fanned out to every channel, so it must fit the SMALLEST of them —
    otherwise the tightest publisher truncates copy the writer thought it had room for."""
    assert channels.draft_max_length([_BSKY, _MASTO]) == 300
    assert channels.draft_max_length([_MASTO, _BSKY]) == 300  # order-independent
    assert channels.draft_max_length([_MASTO]) == 500
    assert channels.draft_max_length([_BSKY]) == 300


def test_draft_max_length_of_no_channels_is_the_bluesky_limit():
    """Load-bearing: every channel-less Persona keeps today's behavior."""
    assert channels.draft_max_length([]) == config.BLUESKY_MAX_GRAPHEMES


# ── handles: never fall back to another platform's identity ──

def test_handle_for_prefers_the_channel_then_the_platforms_own_credential(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "cred.bsky.social")
    assert channels.handle_for(_BSKY) == "gnome.bsky.social"
    assert channels.handle_for({"platform": "bluesky"}) == "cred.bsky.social"


def test_handle_for_never_returns_the_bluesky_handle_for_another_platform(monkeypatch):
    """The bug this replaces: channel_handle fell back to BLUESKY_HANDLE for ANY platform, so a
    Mastodon channel would silently act as the Bluesky account."""
    monkeypatch.setenv("BLUESKY_HANDLE", "cred.bsky.social")
    assert channels.handle_for(_MASTO) == ""


# ── drift guard: the registry's declared capability must match what the adapter actually does ──

def test_declared_actions_match_the_live_bluesky_engager():
    assert channels.channel_spec("bluesky").actions == BlueskySignalEngager.supported_actions


def test_declared_actions_are_a_subset_of_the_vocabulary():
    for platform in channels.known_platforms():
        assert channels.channel_spec(platform).actions <= set(SignalKind)
