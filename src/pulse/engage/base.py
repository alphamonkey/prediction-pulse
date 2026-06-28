"""Engagement vocabulary + seams.

Capability-driven over a normalized action vocabulary, mirroring the metrics seam (`MetricKind`):
an `Engager` declares `supported_actions` so a platform that can't do some action simply doesn't
list it, and richer actions (reply/quote) slot in without changing the vocabulary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class SignalKind(str, Enum):
    """Normalized engagement-action vocabulary. v1 ships the no-copy signals; reply/quote reserved."""

    LIKE = "like"
    REPOST = "repost"
    FOLLOW = "follow"
    REPLY = "reply"   # reserved for a later, LLM-backed reactive engager
    QUOTE = "quote"   # reserved


@dataclass
class Target:
    """Something worth engaging with, produced by a TargetSource and consumed by an Engager."""

    uri: str
    cid: str
    author_did: str
    author_handle: str
    text: str
    source: str          # which TargetSource produced it (e.g. "topical-search")
    score: float = 0.0   # optional relevance score for future ranking


@runtime_checkable
class TargetSource(Protocol):
    """Inbound seam: where engagement targets come from. Topical search now; reciprocal, curated
    lists, and the reverse-poller plug in behind this later."""

    name: str

    def find_targets(self, *, limit: int) -> list[Target]:
        ...


@dataclass
class EngageResult:
    """Outcome of one engagement action. `performed` is False in dryrun (so nothing is recorded)."""

    action: SignalKind
    target_uri: str
    target_did: str
    performed: bool


@runtime_checkable
class Engager(Protocol):
    """Outbound action seam (sibling of Publisher). Declares which actions it can take, so a
    platform that lacks one simply doesn't list it — and reply/quote slot in later unchanged."""

    name: str  # the channel/platform, e.g. "bluesky"
    supported_actions: frozenset[SignalKind]

    def engage(self, target: Target, action: SignalKind) -> EngageResult:
        ...
