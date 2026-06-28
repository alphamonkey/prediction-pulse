"""BlueskyEngagementSource — pulls profile + per-post engagement back via the atproto SDK.

Lazy login on first call (mirrors BlueskyPublisher). Read-only: it never posts. `get_posts` is
capped at 25 URIs per call, so `engagement` batches. Bookmarks are mapped opportunistically (newer
app versions expose `bookmark_count`).
"""

from __future__ import annotations

import logging

from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.models import _now

log = logging.getLogger("pulse")

_GET_POSTS_MAX = 25  # atproto app.bsky.feed.getPosts cap


class BlueskyEngagementSource:
    name = "bluesky"
    supported_metrics = frozenset({
        MetricKind.LIKES, MetricKind.REPOSTS, MetricKind.REPLIES,
        MetricKind.QUOTES, MetricKind.BOOKMARKS,
    })

    def __init__(self, handle: str, app_password: str, *, client=None) -> None:
        self._handle = handle
        self._app_password = app_password
        self._client = client  # injected in tests; login still happens on it
        self._logged_in = False

    def _ensure_login(self):
        if self._client is None:
            from atproto import Client

            self._client = Client()
        if not self._logged_in:
            self._client.login(self._handle, self._app_password)
            self._logged_in = True
        return self._client

    def account(self, handle: str) -> AccountStats:
        client = self._ensure_login()
        p = client.get_profile(handle)
        return AccountStats(
            followers=p.followers_count, follows=p.follows_count, posts=p.posts_count,
            fetched_at=_now(),
        )

    def engagement(self, uris: list[str]) -> list[PostEngagement]:
        if not uris:
            return []
        client = self._ensure_login()
        out: list[PostEngagement] = []
        for i in range(0, len(uris), _GET_POSTS_MAX):
            chunk = uris[i:i + _GET_POSTS_MAX]
            for post in client.get_posts(chunk).posts:
                out.append(self._to_engagement(post))
        return out

    def _to_engagement(self, post) -> PostEngagement:
        metrics = {
            MetricKind.LIKES: post.like_count or 0,
            MetricKind.REPOSTS: post.repost_count or 0,
            MetricKind.REPLIES: post.reply_count or 0,
            MetricKind.QUOTES: post.quote_count or 0,
        }
        bookmarks = getattr(post, "bookmark_count", None)
        if bookmarks is not None:
            metrics[MetricKind.BOOKMARKS] = bookmarks
        return PostEngagement(uri=post.uri, platform=self.name, fetched_at=_now(), metrics=metrics)
