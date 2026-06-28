"""BlueskySignalEngager — takes no-copy engagement actions via the atproto SDK.

v1 signals only: like / repost (keyed on a post's uri+cid) and follow (keyed on the author's did).
Lazy login + injectable client, mirroring BlueskyPublisher. Reply/quote are intentionally absent
from `supported_actions` until a later, LLM-backed engager adds them.
"""

from __future__ import annotations

import logging

from pulse.engage.base import EngageResult, SignalKind, Target

log = logging.getLogger("pulse")


class BlueskySignalEngager:
    name = "bluesky"
    supported_actions = frozenset({SignalKind.LIKE, SignalKind.REPOST, SignalKind.FOLLOW})

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

    def engage(self, target: Target, action: SignalKind) -> EngageResult:
        if action not in self.supported_actions:
            raise ValueError(f"{self.name} engager does not support {action!r}")
        client = self._ensure_login()
        if action is SignalKind.LIKE:
            client.like(target.uri, target.cid)
        elif action is SignalKind.REPOST:
            client.repost(target.uri, target.cid)
        elif action is SignalKind.FOLLOW:
            client.follow(target.author_did)
        log.info("%s %s %s", self.name, action.value, target.uri or target.author_handle)
        return EngageResult(
            action=action, target_uri=target.uri, target_did=target.author_did, performed=True
        )
