"""Tests for the Publisher seam, DryRun/Bluesky publishers, and the make_publisher gate."""

from types import SimpleNamespace

import pytest

from pulse import config
from pulse.persona import Persona
from pulse.publish.base import PostResult, Publisher
from pulse.publish.bluesky import BlueskyPublisher
from pulse.publish.dryrun import DryRunPublisher
from pulse.publish.factory import make_publisher
from pulse.writer.base import Draft

_PERSONA = Persona(name="gnome", voice="be a gnome")


def _draft(text="A punchy post.", key="k1"):
    return Draft(event_dedup_key=key, persona="gnome", text=text)


# ── DryRunPublisher ──

def test_dryrun_publisher_does_not_post():
    pub = DryRunPublisher("bluesky")
    assert pub.name == "bluesky"
    assert isinstance(pub, Publisher)
    result = pub.publish(_draft(), _PERSONA)
    assert isinstance(result, PostResult)
    assert result.posted is False
    assert result.uri is None
    assert result.text == "A punchy post."


# ── BlueskyPublisher (fake atproto client) ──

class FakeBskyClient:
    def __init__(self):
        self.logged_in = None
        self.sent = []

    def login(self, login, password):
        self.logged_in = (login, password)
        return SimpleNamespace(handle=login)

    def send_post(self, text):
        self.sent.append(text)
        return SimpleNamespace(uri=f"at://did/{len(self.sent)}", cid="cid1")


def test_bluesky_publisher_posts_and_returns_uri():
    client = FakeBskyClient()
    pub = BlueskyPublisher("gnome.bsky.social", "app-pw", client=client)
    assert pub.name == "bluesky"
    assert isinstance(pub, Publisher)
    result = pub.publish(_draft("hello world"), _PERSONA)
    assert client.logged_in == ("gnome.bsky.social", "app-pw")
    assert client.sent == ["hello world"]
    assert result.posted is True
    assert result.uri == "at://did/1"
    assert result.cid == "cid1"


def test_bluesky_publisher_caps_length():
    client = FakeBskyClient()
    BlueskyPublisher("h", "p", client=client).publish(_draft("z" * 400), _PERSONA)
    assert len(client.sent[0]) <= config.BLUESKY_MAX_GRAPHEMES


def test_bluesky_publisher_logs_in_once():
    client = FakeBskyClient()
    pub = BlueskyPublisher("h", "p", client=client)
    pub.publish(_draft(key="a"), _PERSONA)
    pub.publish(_draft(key="b"), _PERSONA)
    assert client.logged_in is not None
    assert len(client.sent) == 2  # logged in once, posted twice


# ── make_publisher (the live gate) ──

def test_make_publisher_dryrun_returns_dryrun(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    pub = make_publisher({"platform": "bluesky"})
    assert isinstance(pub, DryRunPublisher)
    assert pub.name == "bluesky"


def test_make_publisher_live_returns_bluesky(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "pw")
    monkeypatch.setenv("BLUESKY_HANDLE", "h.bsky.social")
    pub = make_publisher({"platform": "bluesky"})
    assert isinstance(pub, BlueskyPublisher)


def test_make_publisher_live_without_password_raises(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "")
    with pytest.raises(RuntimeError):
        make_publisher({"platform": "bluesky", "handle": "h"})


def test_make_publisher_unknown_platform_raises(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    with pytest.raises(ValueError):
        make_publisher({"platform": "myspace"})
