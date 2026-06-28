"""TopicalSearchSource — finds engagement targets via Bluesky post search.

The first `TargetSource`: runs the configured topic queries through `app.bsky.feed.searchPosts`
and maps the hits to `Target`s. Lazy login on first use + injectable client, mirroring
`BlueskyPublisher`/`BlueskyEngagementSource`. Read-only — it finds targets but takes no action.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pulse.engage.base import Target

log = logging.getLogger("pulse")


class TopicalSearchSource:
    name = "topical-search"

    def __init__(self, handle: str, app_password: str, *, queries: Iterable[str], client=None) -> None:
        self._handle = handle
        self._app_password = app_password
        self._queries = [q for q in queries if q]
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

    def find_targets(self, *, limit: int) -> list[Target]:
        if limit <= 0 or not self._queries:
            return []
        from atproto import models

        client = self._ensure_login()
        per_query = -(-limit // len(self._queries))  # ceil, so each topic gets a fair share
        out: list[Target] = []
        for query in self._queries:
            resp = client.app.bsky.feed.search_posts(
                models.AppBskyFeedSearchPosts.Params(q=query, limit=per_query, sort="latest")
            )
            for post in resp.posts:
                out.append(self._to_target(post, query))
        return out[:limit]

    @staticmethod
    def _to_target(post, query: str) -> Target:
        return Target(
            uri=post.uri,
            cid=post.cid,
            author_did=post.author.did,
            author_handle=post.author.handle,
            text=getattr(post.record, "text", "") or "",
            source=f"topical-search:{query}",
        )
