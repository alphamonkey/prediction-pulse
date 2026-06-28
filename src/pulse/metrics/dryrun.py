"""NullEngagementSource — the safety default outside live mode: no network, no metrics.

Stands in for every platform when not live, so the metrics cycle is a harmless no-op (zeroed
account stats, no per-post metrics). Mirrors DryRunPublisher.
"""

from __future__ import annotations

from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.models import _now


class NullEngagementSource:
    supported_metrics: frozenset[MetricKind] = frozenset()

    def __init__(self, platform: str) -> None:
        self.name = platform

    def account(self, handle: str) -> AccountStats:
        return AccountStats(followers=0, follows=0, posts=0, fetched_at=_now())

    def engagement(self, uris: list[str]) -> list[PostEngagement]:
        return []
