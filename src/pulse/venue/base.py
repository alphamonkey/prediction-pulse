"""The venue-agnostic seams: where "something to post about" comes from.

`ContentSource` is what the poll job drives: anything that yields the venue's newly recorded
`Event`s. Market snapshot polling is one implementation (`SnapshotContentSource`, wrapping a
`SnapshotSource` + the detector); generated/non-market sources implement `ContentSource`
directly.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pulse.detector.engine import run_detection
from pulse.models import Event, Snapshot

if TYPE_CHECKING:
    from pulse.store.db import Database

log = logging.getLogger("pulse")


@runtime_checkable
class SnapshotSource(Protocol):
    venue: str

    def fetch_snapshots(self, now: datetime) -> list[Snapshot]:
        """Return current normalized snapshots for this venue, timestamped `now`."""
        ...


@runtime_checkable
class ContentSource(Protocol):
    venue: str

    def fetch_events(self, db: Database, now: datetime) -> list[Event]:
        """Return this venue's NEWLY recorded events for this cycle.

        Contract: the source records each emitted event via `db.record_posted` (whose
        INSERT OR IGNORE is the race-safe dedup backstop) and returns only the ones that
        were new — re-emitting a seen dedup_key must yield nothing.
        """
        ...


class SnapshotContentSource:
    """The market implementation of ContentSource: snapshots -> store -> detection.

    `run_detection` records emitted events itself, so the ContentSource contract holds.
    """

    def __init__(self, source: SnapshotSource) -> None:
        self.source = source  # exposed: callers/tests may care which market source is wrapped
        self.venue = source.venue

    def fetch_events(self, db: Database, now: datetime) -> list[Event]:
        snapshots = self.source.fetch_snapshots(now)
        stored = sum(int(db.insert_snapshot(s)) for s in snapshots)
        log.info("%s: %d snapshots seen, %d new", self.venue, len(snapshots), stored)
        return run_detection(db, self.venue)
