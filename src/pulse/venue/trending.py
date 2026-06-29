"""Bluesky-trend-selected Kalshi poller: pick markets by what's trending, not by category.

A peer to `venue/kalshi.py`'s `KalshiSource`. It pulls Bluesky trending topics, matches them to open
Kalshi markets by title, and snapshots only those — far fewer rows than the broad allowlist poll, and
trend-relevant. `venue` stays "kalshi": the snapshots ARE Kalshi markets, so store + detector treat
them identically. This module holds the pure matching helpers; the client + source are below.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from pulse import config
from pulse.models import Snapshot
from pulse.venue.kalshi import KalshiClient, _num, market_to_snapshot

log = logging.getLogger("pulse")

# Common words that carry no entity signal — dropped from keywords/match tokens.
_STOPWORDS = frozenset({
    "the", "vs", "and", "for", "with", "this", "that", "from", "have", "will",
    "your", "you", "are", "was", "were", "his", "her", "its", "out", "new",
})
_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass
class Trend:
    """A normalized Bluesky trend (our own shape, decoupled from the unspecced SDK type)."""

    display_name: str
    post_count: int = 0
    category: str | None = None


class BlueskyTrendClient:
    """Defensive lazy-login wrapper over `app.bsky.unspecced.get_trends`.

    The endpoint is unspecced (experimental), so any failure/empty response degrades to `[]` rather
    than crashing the poll cycle. Injectable client + lazy login, mirroring `publish/bluesky.py`.
    """

    def __init__(self, handle: str, app_password: str, *, client=None) -> None:
        self._handle = handle
        self._app_password = app_password
        self._client = client
        self._logged_in = False

    def _ensure_login(self):
        if self._client is None:
            from atproto import Client

            self._client = Client()
        if not self._logged_in:
            self._client.login(self._handle, self._app_password)
            self._logged_in = True
        return self._client

    def get_trends(self, *, limit: int) -> list[Trend]:
        try:
            client = self._ensure_login()
            resp = client.app.bsky.unspecced.get_trends({"limit": limit})
            raw = getattr(resp, "trends", None) or []
            return [
                Trend(
                    display_name=t.display_name,
                    post_count=getattr(t, "post_count", 0) or 0,
                    category=getattr(t, "category", None),
                )
                for t in raw
            ]
        except Exception:  # noqa: BLE001 — unspecced endpoint; never let it kill the poll
            log.exception("get_trends failed — yielding no trends this cycle")
            return []


def _tokens(text: str) -> set[str]:
    """Significant lowercase word tokens (>=3 chars, non-stopword)."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 3 and t not in _STOPWORDS}


def trend_keyword_groups(trends: Iterable[Trend]) -> list[set[str]]:
    """One token-set per trend (empties dropped). Matching requires ALL tokens of a group to be
    present, so multi-word trends ("World Cup") don't over-match on a single common token."""
    groups: list[set[str]] = []
    for tr in trends:
        toks = _tokens(tr.display_name)
        if toks and toks not in groups:
            groups.append(toks)
    return groups


def market_matches(title: str, groups: Sequence[set[str]]) -> bool:
    """True if the title contains every token of at least one trend group."""
    title_tokens = _tokens(title)
    return any(group <= title_tokens for group in groups)


def select_trending_markets(
    events: Iterable[dict], groups: Sequence[set[str]], now: datetime, *,
    exclude_categories: Sequence[str], min_volume_24h: float, max_markets: int | None = None,
) -> list[Snapshot]:
    """Snapshot the open markets whose market/event title matches a trend group.

    Unlike the broad poll, there is NO category allowlist — trend-relevance is the filter — but the
    project's agriculture/food exclusion and a volume floor still apply. `max_markets` caps the result
    to the highest-volume matches so one broad trend can't balloon the snapshot count.
    """
    if not groups:
        return []
    excluded = {c.lower() for c in exclude_categories}
    snapshots: list[Snapshot] = []
    for event in events:
        category = event.get("category")
        if category and category.lower() in excluded:
            continue
        event_title = event.get("title") or ""
        for market in event.get("markets") or []:
            if market.get("status") != "active":
                continue
            if _num(market, "volume_24h_fp", "volume_24h") < min_volume_24h:
                continue
            title = f"{market.get('title') or ''} {event_title}"
            if not market_matches(title, groups):
                continue
            raw = {
                **market,
                "event_ticker": event.get("event_ticker"),
                "series_ticker": event.get("series_ticker"),
            }
            snap = market_to_snapshot(raw, category, now)
            if snap is not None:
                snapshots.append(snap)
    if max_markets is not None and len(snapshots) > max_markets:
        snapshots.sort(key=lambda s: s.volume, reverse=True)
        snapshots = snapshots[:max_markets]
    return snapshots


class BlueskyTrendSource:
    """SnapshotSource peer to KalshiSource: select Kalshi markets by Bluesky trends, not category.

    `venue` is "kalshi" — the snapshots ARE Kalshi markets, so the store + detector are unchanged.
    """

    venue = "kalshi"

    def __init__(
        self, trend_client: "BlueskyTrendClient", kalshi_client: KalshiClient, *,
        limit: int = config.TREND_LIMIT,
        min_volume_24h: float = config.TREND_MIN_VOLUME_24H,
        exclude_categories: Sequence[str] = config.TREND_EXCLUDE_CATEGORIES,
        max_markets: int = config.TREND_MAX_MARKETS,
    ) -> None:
        self._trend = trend_client
        self._kalshi = kalshi_client
        self._limit = limit
        self._min_volume_24h = min_volume_24h
        self._exclude_categories = exclude_categories
        self._max_markets = max_markets

    def fetch_snapshots(self, now: datetime) -> list[Snapshot]:
        groups = trend_keyword_groups(self._trend.get_trends(limit=self._limit))
        if not groups:
            return []
        return select_trending_markets(
            self._kalshi.iter_open_events(), groups, now,
            exclude_categories=self._exclude_categories, min_volume_24h=self._min_volume_24h,
            max_markets=self._max_markets,
        )
