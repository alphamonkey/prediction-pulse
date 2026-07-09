"""Source registry: resolve a [pipeline.poll] SourceSpec to a ContentSource.

"Get *something* to post about" is one builder registered here — market venues (kalshi,
trend) arrive wrapped in SnapshotContentSource; non-market sources implement ContentSource
directly. Each builder owns the validation of its option keys, and dependencies come lazily
from SourceContext: a persona with no market sources never constructs a Kalshi client.
"""

from __future__ import annotations

from collections.abc import Callable

from pulse import config
from pulse.pipeline import SourceSpec
from pulse.venue.base import ContentSource, SnapshotContentSource
from pulse.venue.kalshi import KalshiClient, KalshiSource
from pulse.venue.trending import BlueskyTrendClient, BlueskyTrendSource


class SourceContext:
    """Lazily built, memoized dependencies for source builders.

    The owner (supervise / the poll CLI) calls `close()` when done; closing without
    materialization is a no-op.
    """

    def __init__(self, kalshi_factory: Callable[[], KalshiClient] = KalshiClient) -> None:
        self._kalshi_factory = kalshi_factory
        self._kalshi: KalshiClient | None = None

    def kalshi(self) -> KalshiClient:
        if self._kalshi is None:
            self._kalshi = self._kalshi_factory()
        return self._kalshi

    def close(self) -> None:
        if self._kalshi is not None:
            self._kalshi.close()
            self._kalshi = None


def _check_options(source_type: str, options: dict, allowed: tuple[str, ...]) -> None:
    unknown = set(options) - set(allowed)
    if unknown:
        raise ValueError(
            f"source {source_type!r} has unknown option(s): {', '.join(sorted(unknown))}")


def _kalshi(options: dict, ctx: SourceContext) -> ContentSource:
    _check_options("kalshi", options, ())
    return SnapshotContentSource(KalshiSource(ctx.kalshi()))


def _trend(options: dict, ctx: SourceContext) -> ContentSource:
    _check_options("trend", options, ())
    return SnapshotContentSource(BlueskyTrendSource(
        BlueskyTrendClient(config.bluesky_handle(), config.bluesky_app_password()),
        ctx.kalshi()))


_BUILDERS: dict[str, Callable[[dict, SourceContext], ContentSource]] = {
    "kalshi": _kalshi,  # broad category-allowlist poll
    "trend": _trend,    # Bluesky-trend-selected markets
}


def make_source(spec: SourceSpec, ctx: SourceContext) -> ContentSource:
    try:
        builder = _BUILDERS[spec.type]
    except KeyError:
        known = ", ".join(sorted(_BUILDERS))
        raise ValueError(f"unknown content source {spec.type!r} (known: {known})") from None
    return builder(spec.options, ctx)
