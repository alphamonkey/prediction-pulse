"""The publish cycle: pick a persona's freshest un-posted drafts, post them (per channel),
record each — idempotently, under the daily cap. Dryrun-safe via make_publisher. Mirrors drafter.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pulse import config
from pulse.persona import Persona
from pulse.publish.base import Publisher
from pulse.publish.factory import make_publisher
from pulse.store.db import Database

log = logging.getLogger("pulse")


@dataclass
class PublishReport:
    candidates: int = 0
    posted: int = 0
    would_post: int = 0  # dryrun
    posts: list = field(default_factory=list)


def publish_once(db: Database, publisher: Publisher, persona: Persona, *, limit: int) -> PublishReport:
    channel = publisher.name
    remaining = max(0, config.MAX_POSTS_PER_DAY - db.posts_today(channel))
    n = min(limit, remaining)
    if n <= 0:
        log.info("publish: daily cap reached for %s", channel)
        return PublishReport()

    drafts = db.get_unposted_drafts(
        channel, persona=persona.name, limit=n, max_age_hours=config.MAX_DRAFT_AGE_HOURS
    )
    posted, would, posts = 0, 0, []
    for draft in drafts:
        try:
            result = publisher.publish(draft, persona)
        except Exception:  # noqa: BLE001 — one failed post must not stop the batch
            log.exception("publish failed for %s on %s", draft.event_dedup_key, channel)
            continue
        if result.posted:
            if db.insert_post(draft.event_dedup_key, persona.name, result):
                posted += 1
                posts.append(result)
                log.info("  posted [%s] %s", channel, result.uri)
        else:
            would += 1
    return PublishReport(candidates=len(drafts), posted=posted, would_post=would, posts=posts)


class PublishJob:
    """The publish cycle as a schedulable Job — loops a persona's channels."""

    name = "publish"

    def __init__(self, db: Database, persona: Persona, *, limit: int) -> None:
        self._db = db
        self._persona = persona
        self._limit = limit

    def run(self) -> PublishReport:
        agg = PublishReport()
        if not self._persona.channels:
            log.warning("persona %s has no channels — nothing to publish", self._persona.name)
        for channel in self._persona.channels:
            r = publish_once(self._db, make_publisher(channel), self._persona, limit=self._limit)
            agg.candidates += r.candidates
            agg.posted += r.posted
            agg.would_post += r.would_post
            agg.posts += r.posts
        log.info("publish complete (mode=%s, persona=%s): %d posted, %d would-post",
                 config.pulse_mode(), self._persona.name, agg.posted, agg.would_post)
        return agg
