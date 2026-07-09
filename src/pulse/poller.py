"""Source-agnostic poll cycle: drive a ContentSource, report its newly recorded events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from pulse import config
from pulse.models import Event, _now
from pulse.store.db import Database
from pulse.venue.base import ContentSource

log = logging.getLogger("pulse")


@dataclass
class PollReport:
    events: list[Event] = field(default_factory=list)


def poll_once(source: ContentSource, db: Database, *, now: datetime | None = None) -> PollReport:
    now = now or _now()
    return PollReport(events=source.fetch_events(db, now))


class PollJob:
    """The poll cycle as a schedulable Job: poll_once + report logging.

    Used by both `pulse poll` (run once) and `pulse run` (run on a schedule), so the report
    logging lives in one place.
    """

    name = "poll"

    def __init__(self, source: ContentSource, db: Database) -> None:
        self._source = source
        self._db = db

    def run(self) -> PollReport:
        report = poll_once(self._source, self._db)
        log.info("poll complete (mode=%s): %d new events",
                 config.pulse_mode(), len(report.events))
        for ev in report.events:
            log.info("  [%s] %s", ev.rule, ev.headline)
        return report
