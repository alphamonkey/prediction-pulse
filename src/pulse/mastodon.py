"""A thin Mastodon REST client, shared by the publish / engage / metrics adapters.

Unlike Bluesky there is no SDK to lean on, so the three seam adapters would otherwise each
re-implement bearer auth and URL building. They ride this instead and stay thin. httpx is already a
dependency (venue/kalshi.py), so Mastodon adds none.

Instance-agnostic on purpose: the base URL is passed in from the channel's declared `instance`, so
one adapter serves any Mastodon-compatible server (Pleroma, Akkoma, GoToSocial too). The token
identifies the account — `verify_credentials` is how we learn who we are — so a Mastodon channel
needs exactly ONE secret, where Bluesky needs a handle and a password.
"""

from __future__ import annotations

import logging
import re
from html import unescape

from pulse.config import HTTP_TIMEOUT_SECONDS

log = logging.getLogger("pulse")

_TAGS = re.compile(r"<[^>]+>")
_NON_TAG_CHARS = re.compile(r"[^0-9a-z]+")


def strip_html(content: str) -> str:
    """Mastodon serves status content as HTML. The engage relevance/safety filter substring-matches
    plain text, so markup must go — or the filter matches tags instead of words."""
    return unescape(_TAGS.sub("", content or "")).strip()


def to_tag(query: str) -> str:
    """A search query as a Mastodon hashtag: the tag timeline is the only free text-ish search that
    every instance exposes (full-text search is opt-in per instance)."""
    return _NON_TAG_CHARS.sub("", query.lower())


class MastodonClient:
    def __init__(self, instance: str, token: str, *, http=None) -> None:
        self._base = instance.rstrip("/")
        self._token = token
        self.http = http  # injected in tests

    def _client(self):
        if self.http is None:
            import httpx

            self.http = httpx.Client(timeout=HTTP_TIMEOUT_SECONDS)
        return self.http

    def _request(self, method: str, path: str, **kwargs):
        response = self._client().request(
            method, f"{self._base}{path}",
            headers={"Authorization": f"Bearer {self._token}"}, **kwargs,
        )
        response.raise_for_status()
        return response.json()

    # ── reads ──
    def verify_credentials(self) -> dict:
        return self._request("GET", "/api/v1/accounts/verify_credentials")

    def status(self, status_id: str) -> dict:
        return self._request("GET", f"/api/v1/statuses/{status_id}")

    def tag_timeline(self, tag: str, *, limit: int) -> list[dict]:
        return self._request("GET", f"/api/v1/timelines/tag/{tag}", params={"limit": limit})

    # ── writes ──
    def post_status(self, text: str) -> dict:
        return self._request("POST", "/api/v1/statuses", json={"status": text})

    def favourite(self, status_id: str) -> dict:
        return self._request("POST", f"/api/v1/statuses/{status_id}/favourite")

    def reblog(self, status_id: str) -> dict:
        return self._request("POST", f"/api/v1/statuses/{status_id}/reblog")

    def follow(self, account_id: str) -> dict:
        return self._request("POST", f"/api/v1/accounts/{account_id}/follow")

    def close(self) -> None:
        if self.http is not None:
            self.http.close()
