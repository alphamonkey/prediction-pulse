"""Chunk 4: the Engager seam, Bluesky/DryRun impls, and the make_engager live gate."""

from __future__ import annotations

import pytest

from pulse import config
from pulse.engage.base import Engager, EngageResult, SignalKind, Target
from pulse.engage.bluesky import BlueskySignalEngager
from pulse.engage.dryrun import DryRunEngager
from pulse.engage.factory import make_engager


def _target():
    return Target(uri="at://x/1", cid="cid1", author_did="did:plc:a",
                  author_handle="a.bsky.social", text="kalshi", source="topical-search")


class _FakeClient:
    def __init__(self):
        self.calls = []
        self.logins = []

    def login(self, h, pw):
        self.logins.append((h, pw))

    def like(self, uri, cid):
        self.calls.append(("like", uri, cid))

    def repost(self, uri, cid):
        self.calls.append(("repost", uri, cid))

    def follow(self, subject):
        self.calls.append(("follow", subject))


# ── BlueskySignalEngager ──
def test_is_an_engager_with_signal_capabilities():
    eng = BlueskySignalEngager("h", "pw", client=_FakeClient())
    assert isinstance(eng, Engager)
    assert eng.supported_actions == frozenset(
        {SignalKind.LIKE, SignalKind.REPOST, SignalKind.FOLLOW})
    assert SignalKind.REPLY not in eng.supported_actions


def test_like_calls_client_like():
    c = _FakeClient()
    eng = BlueskySignalEngager("h", "pw", client=c)
    result = eng.engage(_target(), SignalKind.LIKE)
    assert c.calls == [("like", "at://x/1", "cid1")]
    assert isinstance(result, EngageResult)
    assert result.performed and result.action == SignalKind.LIKE


def test_repost_calls_client_repost():
    c = _FakeClient()
    BlueskySignalEngager("h", "pw", client=c).engage(_target(), SignalKind.REPOST)
    assert c.calls == [("repost", "at://x/1", "cid1")]


def test_follow_calls_client_follow_with_did():
    c = _FakeClient()
    BlueskySignalEngager("h", "pw", client=c).engage(_target(), SignalKind.FOLLOW)
    assert c.calls == [("follow", "did:plc:a")]


def test_unsupported_action_raises():
    eng = BlueskySignalEngager("h", "pw", client=_FakeClient())
    with pytest.raises(ValueError):
        eng.engage(_target(), SignalKind.REPLY)


# ── DryRunEngager ──
def test_dryrun_performs_nothing():
    eng = DryRunEngager("bluesky")
    result = eng.engage(_target(), SignalKind.LIKE)
    assert eng.name == "bluesky"
    assert result.performed is False
    assert result.action == SignalKind.LIKE


# ── make_engager (the live gate) ──
def test_make_engager_dryrun_returns_dryrun(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    assert isinstance(make_engager({"platform": "bluesky"}), DryRunEngager)


def test_make_engager_live_returns_bluesky(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "pw")
    monkeypatch.setenv("BLUESKY_HANDLE", "h.bsky.social")
    assert isinstance(make_engager({"platform": "bluesky"}), BlueskySignalEngager)


def test_make_engager_live_without_password_raises(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "")
    with pytest.raises(RuntimeError):
        make_engager({"platform": "bluesky", "handle": "h"})


def test_make_engager_unknown_platform_raises(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    with pytest.raises(ValueError):
        make_engager({"platform": "myspace"})
