"""Source registry: [pipeline.poll] source specs resolve to ContentSource builders.

Builders own the validation of their option keys, and dependencies (the Kalshi client)
are built lazily via SourceContext — a persona with no market sources never touches Kalshi.
"""

from __future__ import annotations

import pytest

from pulse.pipeline import SourceSpec
from pulse.venue.base import ContentSource, SnapshotContentSource
from pulse.venue.kalshi import KalshiClient, KalshiSource
from pulse.venue.registry import SourceContext, make_source
from pulse.venue.trending import BlueskyTrendSource


@pytest.fixture
def ctx():
    c = SourceContext()
    yield c
    c.close()


def test_kalshi_source(ctx):
    src = make_source(SourceSpec("kalshi"), ctx)
    assert isinstance(src, ContentSource)
    assert isinstance(src, SnapshotContentSource)
    assert isinstance(src.source, KalshiSource)


def test_trend_source(ctx):
    src = make_source(SourceSpec("trend"), ctx)
    assert isinstance(src, SnapshotContentSource)
    assert isinstance(src.source, BlueskyTrendSource)


def test_unknown_source_names_the_known_ones(ctx):
    with pytest.raises(ValueError, match="rss.*kalshi.*trend"):
        make_source(SourceSpec("rss"), ctx)


def test_unknown_option_key_names_the_source(ctx):
    with pytest.raises(ValueError, match=r"kalshi.*bogus"):
        make_source(SourceSpec("kalshi", {"bogus": 1}), ctx)


class _CountingClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_context_builds_kalshi_lazily_and_memoizes():
    built = []

    def factory():
        client = _CountingClient()
        built.append(client)
        return client

    ctx = SourceContext(kalshi_factory=factory)
    assert built == []  # nothing built until a builder asks
    a = ctx.kalshi()
    b = ctx.kalshi()
    assert a is b and len(built) == 1  # memoized
    ctx.close()
    assert built[0].closed


def test_context_close_without_materialization_is_a_noop():
    ctx = SourceContext(kalshi_factory=KalshiClient)
    ctx.close()  # no client was ever built; must not raise
