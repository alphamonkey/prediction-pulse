"""BlueskyPublisher — posts a draft to Bluesky via the atproto SDK.

Lazy login on first publish (so construction is cheap and a client can be injected for tests).
Text is capped to Bluesky's 300-grapheme limit (the SDK doesn't enforce it).
"""

from __future__ import annotations

import logging

from pulse import config
from pulse.persona import Persona
from pulse.publish.base import PostResult
from pulse.writer.base import Draft, enforce_length

log = logging.getLogger("pulse")


class BlueskyPublisher:
    name = "bluesky"
    max_length = config.BLUESKY_MAX_GRAPHEMES

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

    def publish(self, draft: Draft, persona: Persona) -> PostResult:
        client = self._ensure_login()
        text = enforce_length(draft.text, self.max_length)
        resp = client.send_post(text)
        return PostResult(channel=self.name, posted=True, uri=resp.uri, cid=resp.cid, text=text)
