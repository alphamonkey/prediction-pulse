"""MastodonPublisher — posts a draft to a Mastodon-compatible instance.

`max_length` is a constructor arg, not a constant: instances configure their own limit, and the
channel may declare it. PostResult.uri carries the numeric status id (what the metrics read needs,
so it round-trips through posts.uri); cid carries the permalink, useful for a later link-out.
"""

from __future__ import annotations

import logging

from pulse import config
from pulse.mastodon import MastodonClient
from pulse.persona import Persona
from pulse.publish.base import PostResult
from pulse.writer.base import Draft, enforce_length

log = logging.getLogger("pulse")


class MastodonPublisher:
    name = "mastodon"

    def __init__(self, instance: str = "", token: str = "", *,
                 max_length: int = config.MASTODON_MAX_CHARS, client: MastodonClient | None = None
                 ) -> None:
        self.max_length = max_length
        self._client = client or MastodonClient(instance, token)

    def publish(self, draft: Draft, persona: Persona) -> PostResult:
        text = enforce_length(draft.text, self.max_length)
        status = self._client.post_status(text)
        return PostResult(channel=self.name, posted=True, uri=str(status["id"]),
                          cid=status.get("url"), text=text)
