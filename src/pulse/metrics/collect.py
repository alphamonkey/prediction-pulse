"""The metrics collect cycle: snapshot the account, refresh recent posts' engagement, persist.

Simple by design — fetch *current* counts and upsert them (no diffing, no per-post time-series). The
only series kept is account-level follower growth. Mirrors publisher.py / drafter.py. A source with
no supported metrics (the Null source outside live mode) is inert, so the cycle is a safe no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pulse import config
from pulse.metrics.base import EngagementSource
from pulse.store.db import Database

log = logging.getLogger("pulse")


@dataclass
class MetricsReport:
    followers: int | None = None
    posts_measured: int = 0


def collect_once(db: Database, source: EngagementSource, *, handle: str,
                 post_limit: int) -> MetricsReport:
    if not source.supported_metrics:
        log.info("metrics: %s source is inert (mode=%s) — nothing collected",
                 source.name, config.PULSE_MODE)
        return MetricsReport()

    stats = source.account(handle)
    db.insert_account_snapshot(stats)
    uris = db.recent_post_uris(source.name, post_limit)
    engagement = source.engagement(uris)
    db.upsert_post_metrics(engagement)
    log.info("metrics complete (%s): followers=%d, posts measured=%d",
             source.name, stats.followers, len(engagement))
    return MetricsReport(followers=stats.followers, posts_measured=len(engagement))


class MetricsJob:
    """The metrics collect cycle as a schedulable Job."""

    name = "metrics"

    def __init__(self, db: Database, source: EngagementSource, *, handle: str,
                 post_limit: int) -> None:
        self._db = db
        self._source = source
        self._handle = handle
        self._post_limit = post_limit

    def run(self) -> MetricsReport:
        return collect_once(self._db, self._source, handle=self._handle,
                            post_limit=self._post_limit)
