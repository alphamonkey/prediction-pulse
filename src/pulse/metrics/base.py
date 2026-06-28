"""The metrics seam: pull engagement back from a platform, behind a swappable interface.

Platforms expose different metric sets — Bluesky a handful of counts, X/Twitter a superset
(impressions, bookmarks, link/profile clicks, video views). So this seam is **capability-driven over
a normalized vocabulary**, never hard-coded to one platform's shape:

- `MetricKind` is the shared vocabulary (stored as plain strings).
- `PostEngagement` carries a metric *bag* (`{MetricKind: int}`), so a source reports only what it has.
- An `EngagementSource` declares `supported_metrics`, so the dashboard can light up only the cards a
  platform actually provides (e.g. an impressions-based engagement rate when a richer source exists).

`make_engagement_source` (factory.py) returns a real source only in live mode — otherwise a
NullEngagementSource — so collection touches no network until deliberately switched.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol, runtime_checkable


class MetricKind(str, Enum):
    """Normalized cross-platform engagement vocabulary. Extend as platforms need."""

    LIKES = "likes"
    REPOSTS = "reposts"
    REPLIES = "replies"
    QUOTES = "quotes"
    BOOKMARKS = "bookmarks"
    IMPRESSIONS = "impressions"
    LINK_CLICKS = "link_clicks"
    PROFILE_CLICKS = "profile_clicks"
    VIDEO_VIEWS = "video_views"


@dataclass
class AccountStats:
    """The near-universal account-level counts (a wide shape is fine here)."""

    followers: int
    follows: int
    posts: int
    fetched_at: datetime


@dataclass
class PostEngagement:
    """Latest engagement for one post — a metric *bag*, so each platform reports only its own set."""

    uri: str
    platform: str
    fetched_at: datetime
    metrics: dict[MetricKind, int] = field(default_factory=dict)


@runtime_checkable
class EngagementSource(Protocol):
    name: str  # the channel/platform, e.g. "bluesky"
    supported_metrics: frozenset[MetricKind]  # capability declaration

    def account(self, handle: str) -> AccountStats:
        ...

    def engagement(self, uris: list[str]) -> list[PostEngagement]:
        ...
