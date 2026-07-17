"""MastodonEngagementSource — pulls the account's counts + per-post engagement back.

Read-only. A narrower metric set than Bluesky's (no quotes, no bookmarks), which is exactly what
the MetricKind capability bag exists for: a platform reports only what it has.

`account()` ignores its handle argument — the bearer token already identifies the account, so
verify_credentials is authoritative. There is no batch status endpoint, so per-post reads are a
loop; the metrics cycle is hourly over ~50 posts, well inside any instance's rate limit.
"""

from __future__ import annotations

import logging

from pulse.mastodon import MastodonClient
from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.models import _now

log = logging.getLogger("pulse")


class MastodonEngagementSource:
    name = "mastodon"
    supported_metrics = frozenset({MetricKind.LIKES, MetricKind.REPOSTS, MetricKind.REPLIES})

    def __init__(self, instance: str = "", token: str = "", *,
                 client: MastodonClient | None = None) -> None:
        self._client = client or MastodonClient(instance, token)

    def account(self, handle: str) -> AccountStats:
        me = self._client.verify_credentials()
        return AccountStats(
            followers=me.get("followers_count", 0),
            follows=me.get("following_count", 0),
            posts=me.get("statuses_count", 0),
            fetched_at=_now(),
        )

    def engagement(self, uris: list[str]) -> list[PostEngagement]:
        out: list[PostEngagement] = []
        for uri in uris:
            status = self._client.status(uri)
            out.append(PostEngagement(
                uri=str(status["id"]), platform=self.name, fetched_at=_now(),
                metrics={
                    MetricKind.LIKES: status.get("favourites_count", 0),
                    MetricKind.REPOSTS: status.get("reblogs_count", 0),
                    MetricKind.REPLIES: status.get("replies_count", 0),
                },
            ))
        return out
