"""The metrics collect cycle: snapshot the account, refresh recent posts' engagement, persist.

Simple by design — fetch *current* counts and upsert them (no diffing, no per-post time-series). The
only series kept is account-level follower growth. Mirrors publisher.py / drafter.py. A source with
no supported metrics (the Null source outside live mode) is inert, so the cycle is a safe no-op.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pulse import config
from pulse.metrics.base import EngagementSource
from pulse.metrics.factory import make_engagement_source
from pulse.persona import Persona
from pulse.store.db import Database

log = logging.getLogger("pulse")


@dataclass
class MetricsReport:
    followers: int | None = None          # summed across channels (the persona's total audience)
    posts_measured: int = 0
    by_platform: dict = field(default_factory=dict)  # platform -> followers, kept separate


def collect_once(db: Database, source: EngagementSource, *, handle: str,
                 post_limit: int) -> MetricsReport:
    if not source.supported_metrics:
        log.info("metrics: %s source is inert (mode=%s) — nothing collected",
                 source.name, config.pulse_mode())
        return MetricsReport()

    stats = source.account(handle)
    db.insert_account_snapshot(stats, platform=source.name)
    uris = db.recent_post_uris(source.name, post_limit)
    engagement = source.engagement(uris)
    db.upsert_post_metrics(engagement)
    log.info("metrics complete (%s): followers=%d, posts measured=%d",
             source.name, stats.followers, len(engagement))
    return MetricsReport(followers=stats.followers, posts_measured=len(engagement))


class MetricsJob:
    """The metrics collect cycle as a schedulable Job — loops a persona's channels.

    A sibling of PublishJob and EngageJob, which have always looped. This one used to be built with
    a hard-coded "bluesky", so a persona's other accounts were simply never measured.
    """

    name = "metrics"

    def __init__(self, db: Database, persona: Persona, *, post_limit: int) -> None:
        self._db = db
        self._persona = persona
        self._post_limit = post_limit

    def run(self) -> MetricsReport:
        agg = MetricsReport()
        if not self._persona.channels:
            log.warning("persona %s has no channels — nothing to collect", self._persona.name)
        for channel in self._persona.channels:
            platform = channel["platform"]
            r = collect_once(self._db, make_engagement_source(channel),
                             handle=self._persona.channel_handle(platform),
                             post_limit=self._post_limit)
            agg.posts_measured += r.posts_measured
            if r.followers is not None:
                agg.followers = (agg.followers or 0) + r.followers
                agg.by_platform[platform] = r.followers
        return agg
