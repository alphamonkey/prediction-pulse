"""Mastodon engagement: the outbound signal engager + a tag-timeline target source.

Unlike X — where automated likes and follows are prohibited outright — Mastodon permits every
signal in the vocabulary, so `supported_actions` is the full set.

MastodonTagSource searches the hashtag timeline: it's the one text-ish search every instance
exposes (full-text search is opt-in per instance, so relying on it would break instance-agnosticism).
Status content arrives as HTML and is stripped before it reaches the relevance/safety filter, which
substring-matches plain text.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from pulse.engage.base import EngageResult, SignalKind, Target
from pulse.mastodon import MastodonClient, strip_html, to_tag

log = logging.getLogger("pulse")


class MastodonSignalEngager:
    name = "mastodon"
    supported_actions = frozenset({SignalKind.LIKE, SignalKind.REPOST, SignalKind.FOLLOW})

    def __init__(self, instance: str = "", token: str = "", *,
                 client: MastodonClient | None = None) -> None:
        self._client = client or MastodonClient(instance, token)

    def engage(self, target: Target, action: SignalKind) -> EngageResult:
        if action not in self.supported_actions:
            raise ValueError(f"{self.name} engager does not support {action.value!r}")
        if action is SignalKind.LIKE:
            self._client.favourite(target.uri)
        elif action is SignalKind.REPOST:
            self._client.reblog(target.uri)
        elif action is SignalKind.FOLLOW:
            self._client.follow(target.author_did)
        log.info("%s %s %s", self.name, action.value, target.uri or target.author_handle)
        return EngageResult(
            action=action, target_uri=target.uri, target_did=target.author_did, performed=True
        )


class MastodonTagSource:
    name = "mastodon-tag"

    def __init__(self, instance: str = "", token: str = "", *, queries: Iterable[str],
                 client: MastodonClient | None = None) -> None:
        self._queries = [q for q in queries if q]
        self._client = client or MastodonClient(instance, token)

    def find_targets(self, *, limit: int) -> list[Target]:
        if limit <= 0 or not self._queries:
            return []
        per_query = -(-limit // len(self._queries))  # ceil, so each topic gets a fair share
        out: list[Target] = []
        for query in self._queries:
            tag = to_tag(query)
            if not tag:
                continue
            for status in self._client.tag_timeline(tag, limit=per_query):
                out.append(self._to_target(status, query))
        return out[:limit]

    def _to_target(self, status: dict, query: str) -> Target:
        account = status.get("account", {})
        return Target(
            uri=str(status["id"]),
            cid="",                                    # Mastodon has no content hash
            author_did=str(account.get("id", "")),     # the account id follow() needs
            author_handle=account.get("acct", ""),
            text=strip_html(status.get("content", "")),
            source=f"{self.name}:{query}",
        )
