"""Chunk 3: TopicalSearchSource — turns Bluesky search hits into Targets."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pulse.engage.base import Target, TargetSource
from pulse.engage.search import TopicalSearchSource


def _post(uri, text, *, did="did:plc:a", handle="a.bsky.social", cid="cid1"):
    return SimpleNamespace(
        uri=uri, cid=cid,
        author=SimpleNamespace(did=did, handle=handle),
        record=SimpleNamespace(text=text),
    )


class _FakeFeed:
    def __init__(self, by_query):
        self._by_query = by_query
        self.calls = []

    def search_posts(self, params):
        self.calls.append(params)
        return SimpleNamespace(posts=self._by_query.get(params.q, []), cursor=None)


class _FakeClient:
    def __init__(self, by_query):
        self.feed = _FakeFeed(by_query)
        self.app = SimpleNamespace(bsky=SimpleNamespace(feed=self.feed))
        self.logins = []

    def login(self, handle, pw):
        self.logins.append((handle, pw))


def _source(by_query, queries):
    client = _FakeClient(by_query)
    src = TopicalSearchSource("gnome.bsky.social", "pw", queries=queries, client=client)
    return src, client


def test_is_a_targetsource():
    src, _ = _source({}, ["kalshi"])
    assert isinstance(src, TargetSource)
    assert src.name == "topical-search"


def test_maps_search_hits_to_targets():
    by_q = {"kalshi": [_post("at://x/1", "Kalshi odds wild", did="did:plc:z", handle="z.bsky.social")]}
    src, _ = _source(by_q, ["kalshi"])
    targets = src.find_targets(limit=10)
    assert len(targets) == 1
    t = targets[0]
    assert isinstance(t, Target)
    assert (t.uri, t.cid, t.author_did, t.author_handle) == (
        "at://x/1", "cid1", "did:plc:z", "z.bsky.social")
    assert t.text == "Kalshi odds wild"
    assert "kalshi" in t.source


def test_queries_each_configured_topic():
    by_q = {"kalshi": [_post("at://x/1", "a")], "prediction market": [_post("at://x/2", "b")]}
    src, client = _source(by_q, ["kalshi", "prediction market"])
    targets = src.find_targets(limit=10)
    queried = {p.q for p in client.feed.calls}
    assert queried == {"kalshi", "prediction market"}
    assert {t.uri for t in targets} == {"at://x/1", "at://x/2"}


def test_respects_overall_limit():
    by_q = {"kalshi": [_post(f"at://x/{i}", "t") for i in range(10)]}
    src, _ = _source(by_q, ["kalshi"])
    assert len(src.find_targets(limit=3)) == 3


def test_logs_in_on_first_use():
    src, client = _source({"kalshi": []}, ["kalshi"])
    src.find_targets(limit=5)
    assert client.logins == [("gnome.bsky.social", "pw")]
