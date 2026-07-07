"""The persona supervisor: one process runs everything a persona's [pipeline] declares.

`build_supervised` is pure assembly — spec in, (job, scheduler) pairs out, reusing the existing
factories so the dryrun/live gates stay exactly where they were. `supervise` drives each
scheduler on its own thread; all threads share one stop Event, so SIGTERM (wired by the CLI)
winds the whole persona down together. A persona always gets a daily prune job for its own DB.

Every job gets its OWN Database connection to the persona's file — the same concurrency model
as the old process-per-stage layout, with WAL + busy_timeout serializing across connections.
Sharing one connection across job threads is unsafe: Database's lock covers writes only, so an
in-flight read cursor on one thread makes another thread's wal_checkpoint fail with "database
table is locked" (prune hit this live at the gnome cutover).

This is what `pulse supervise <name>` (and the pulse@<name> systemd template) runs.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pulse import config
from pulse.drafter import DraftJob
from pulse.engager import EngageJob, EngagePolicy
from pulse.metrics.collect import MetricsJob
from pulse.metrics.factory import make_engagement_source
from pulse.persona import Persona
from pulse.poller import PollJob
from pulse.pruner import PruneJob
from pulse.publisher import PublishJob
from pulse.scheduler.base import Job, Scheduler
from pulse.scheduler.interval import IntervalScheduler
from pulse.scheduler.windowed import WindowedScheduler
from pulse.store.db import Database
from pulse.venue.kalshi import KalshiClient
from pulse.venue.registry import make_source
from pulse.writer.factory import make_writer

log = logging.getLogger("pulse")


@dataclass(frozen=True)
class SupervisedJob:
    name: str  # unique within the persona, e.g. "poll:trend", "draft", "prune"
    job: Job
    scheduler: Scheduler
    db: Database  # this job's OWN connection (closed by supervise)


def build_supervised(
    persona: Persona, make_db: Callable[[], Database], *,
    kalshi_client: KalshiClient | None = None, max_iterations: int = 0,
) -> list[SupervisedJob]:
    """Assemble the persona's declared jobs, each paired with its scheduler and its own
    Database connection (from `make_db`).

    Publish/engage get WindowedSchedulers (dayparted outward actions); everything else runs
    24/7 on IntervalSchedulers. Prune is always included — every persona owns its DB's retention.
    """
    spec = persona.pipeline
    entries: list[SupervisedJob] = []

    if spec.poll:
        if kalshi_client is None:
            raise ValueError(f"persona {persona.name} declares [pipeline.poll] "
                             "but no kalshi_client was provided")
        for source_name in spec.poll.sources:
            db = make_db()
            job = PollJob(make_source(source_name, kalshi_client), db)
            entries.append(SupervisedJob(f"poll:{source_name}", job, IntervalScheduler(
                job, spec.poll.interval,
                max_iterations=max_iterations, jitter_seconds=spec.poll.jitter), db))

    if spec.draft:
        db = make_db()
        job = DraftJob(db, make_writer(), persona, limit=spec.draft.limit)
        entries.append(SupervisedJob("draft", job, IntervalScheduler(
            job, spec.draft.interval,
            max_iterations=max_iterations, jitter_seconds=spec.draft.jitter), db))

    if spec.publish:
        db = make_db()
        job = PublishJob(db, persona, limit=spec.publish.limit)
        entries.append(SupervisedJob("publish", job, WindowedScheduler(
            job, spec.publish.interval, windows=spec.publish.windows, tz=spec.publish.tz,
            max_iterations=max_iterations, jitter_seconds=spec.publish.jitter), db))

    if spec.engage:
        db = make_db()
        job = EngageJob(db, persona, EngagePolicy.from_spec(spec.engage),
                        limit=spec.engage.limit)
        entries.append(SupervisedJob("engage", job, WindowedScheduler(
            job, spec.engage.interval, windows=spec.engage.windows, tz=spec.engage.tz,
            max_iterations=max_iterations, jitter_seconds=spec.engage.jitter), db))

    if spec.metrics:
        db = make_db()
        job = MetricsJob(db, make_engagement_source("bluesky"),
                         handle=persona.channel_handle("bluesky"),
                         post_limit=spec.metrics.post_limit)
        entries.append(SupervisedJob("metrics", job, IntervalScheduler(
            job, spec.metrics.interval,
            max_iterations=max_iterations, jitter_seconds=spec.metrics.jitter), db))

    # Retention is not opt-in: each persona's DB gets its daily prune.
    db = make_db()
    prune = PruneJob(db)
    entries.append(SupervisedJob("prune", prune, IntervalScheduler(
        prune, config.PRUNE_INTERVAL_SECONDS, max_iterations=max_iterations), db))

    return entries


def supervise(
    persona: Persona, db_path: str | Path, *, max_iterations: int = 0,
    stop: threading.Event | None = None,
) -> None:
    """Run all of the persona's jobs until stop is set (or every scheduler hits max_iterations)."""
    stop = stop or threading.Event()
    kalshi_client = KalshiClient() if persona.pipeline.poll else None
    entries: list[SupervisedJob] = []

    def make_db() -> Database:
        db = Database(db_path)
        db.connect()
        return db

    try:
        entries = build_supervised(persona, make_db, kalshi_client=kalshi_client,
                                   max_iterations=max_iterations)
        log.info("supervisor: persona=%s mode=%s jobs=[%s]",
                 persona.name, config.pulse_mode(), ", ".join(e.name for e in entries))
        threads = [
            threading.Thread(target=e.scheduler.run, args=(stop,),
                             name=f"pulse-{persona.name}-{e.name}")
            for e in entries
        ]
        for t in threads:
            t.start()
        # Join with a timeout so the main thread keeps handling signals (SIGTERM sets `stop`).
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=0.2)
        log.info("supervisor: persona=%s all jobs stopped", persona.name)
    finally:
        for entry in entries:
            entry.db.close()
        if kalshi_client is not None:
            kalshi_client.close()
