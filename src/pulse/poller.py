"""Venue-agnostic poll cycle: fetch normalized snapshots, store them, run detection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

from pulse import config
from pulse.detector.engine import run_detection
from pulse.models import Event, _now
from pulse.store.db import Database
from pulse.venue.base import SnapshotSource

log = logging.getLogger("pulse")


@dataclass
class PollReport:
    markets_seen: int = 0
    snapshots_stored: int = 0
    events: list[Event] = field(default_factory=list)


def poll_once(source: SnapshotSource, db: Database, *, now: datetime | None = None) -> PollReport:
    now = now or _now()
    snapshots = source.fetch_snapshots(now)
    stored = sum(int(db.insert_snapshot(s)) for s in snapshots)
    events = run_detection(db, source.venue)
    return PollReport(markets_seen=len(snapshots), snapshots_stored=stored, events=events)


class PollJob:
    """The poll cycle as a schedulable Job: poll_once + report logging.

    Used by both `pulse poll` (run once) and `pulse run` (run on a schedule), so the report
    logging lives in one place.
    """

    name = "poll"

    def __init__(self, source: SnapshotSource, db: Database) -> None:
        self._source = source
        self._db = db

    def run(self) -> PollReport:
        report = poll_once(self._source, self._db)
        log.info(
            "poll complete (mode=%s): %d markets, %d new snapshots, %d events",
            config.pulse_mode(), report.markets_seen, report.snapshots_stored, len(report.events),
        )
        for ev in report.events:
            log.info("  [%s] %s", ev.rule, ev.headline)
        return report
