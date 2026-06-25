"""The draft cycle: pick undrafted events, rank+cap them, write drafts, store (dryrun — no publish).

Selection caps how many events reach the (paid) writer; idempotency means a re-run drafts nothing
already drafted. `DraftJob` makes the cycle schedulable later, mirroring `PollJob`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pulse.persona import Persona
from pulse.store.db import Database
from pulse.writer.base import Draft, Writer
from pulse.writer.select import select_events

log = logging.getLogger("pulse")


@dataclass
class DraftReport:
    candidates: int = 0
    drafted: int = 0
    drafts: list = field(default_factory=list)


def draft_once(db: Database, writer: Writer, persona: Persona, *, limit: int) -> DraftReport:
    candidates = db.get_undrafted_events()
    selected = select_events(candidates, limit=limit)
    drafts: list[Draft] = []
    for event in selected:
        draft = writer.write(event, persona)
        if db.insert_draft(draft):
            drafts.append(draft)
            log.info("  draft [%s] %s", event.rule, draft.text)
    return DraftReport(candidates=len(candidates), drafted=len(drafts), drafts=drafts)


class DraftJob:
    """The draft cycle as a schedulable Job."""

    name = "draft"

    def __init__(self, db: Database, writer: Writer, persona: Persona, *, limit: int) -> None:
        self._db = db
        self._writer = writer
        self._persona = persona
        self._limit = limit

    def run(self) -> DraftReport:
        report = draft_once(self._db, self._writer, self._persona, limit=self._limit)
        log.info("draft complete: %d candidates, %d new drafts (persona=%s)",
                 report.candidates, report.drafted, self._persona.name)
        return report
