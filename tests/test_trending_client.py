"""Chunk 2: BlueskyTrendClient — defensive wrapper over the unspecced get_trends."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pulse.venue.trending import BlueskyTrendClient, Trend


def _trend(name, posts=0, cat=None):
    return SimpleNamespace(display_name=name, post_count=posts, category=cat)


class _FakeUnspecced:
    def __init__(self, trends=None, raise_=False):
        self._trends = trends
        self._raise = raise_
        self.calls = []

    def get_trends(self, params):
        self.calls.append(params)
        if self._raise:
            raise RuntimeError("unspecced boom")
        return SimpleNamespace(trends=self._trends if self._trends is not None else [])


class _FakeClient:
    def __init__(self, **kw):
        self.unspecced = _FakeUnspecced(**kw)
        self.app = SimpleNamespace(bsky=SimpleNamespace(unspecced=self.unspecced))
        self.logins = []

    def login(self, h, p):
        self.logins.append((h, p))


def _client(**kw):
    fc = _FakeClient(**kw)
    return BlueskyTrendClient("h.bsky.social", "pw", client=fc), fc


def test_returns_normalized_trends():
    src, _ = _client(trends=[_trend("Germany", 100, "sports"), _trend("Ken Paxton", 5, "politics")])
    trends = src.get_trends(limit=10)
    assert all(isinstance(t, Trend) for t in trends)
    assert (trends[0].display_name, trends[0].post_count, trends[0].category) == (
        "Germany", 100, "sports")
    assert trends[1].display_name == "Ken Paxton"


def test_logs_in_on_first_use():
    src, fc = _client(trends=[])
    src.get_trends(limit=5)
    assert fc.logins == [("h.bsky.social", "pw")]


def test_passes_limit():
    src, fc = _client(trends=[])
    src.get_trends(limit=7)
    assert fc.unspecced.calls[0]["limit"] == 7


def test_empty_response_yields_empty_list():
    src, _ = _client(trends=[])
    assert src.get_trends(limit=5) == []


def test_defensive_on_failure_returns_empty():
    src, _ = _client(raise_=True)
    assert src.get_trends(limit=5) == []  # unspecced endpoint failing must not crash the poll
