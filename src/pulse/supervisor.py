"""The persona supervisor: one process runs everything a persona's [pipeline] declares.

`build_supervised` is pure assembly — spec in, (job, scheduler) pairs out, reusing the existing
factories so the dryrun/live gates stay exactly where they were. `supervise` drives each
scheduler on its own thread; all threads share one stop Event, so SIGTERM (wired by the CLI)
winds the whole persona down together. A persona always gets a daily prune job for its own DB.

This is what `pulse supervise <name>` (and the pulse@<name> systemd template) runs.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

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


def build_supervised(
    persona: Persona, db: Database, *, kalshi_client: KalshiClient | None = None,
    max_iterations: int = 0,
) -> list[SupervisedJob]:
    """Assemble the persona's declared jobs, each paired with its scheduler.

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
            job = PollJob(make_source(source_name, kalshi_client), db)
            entries.append(SupervisedJob(f"poll:{source_name}", job, IntervalScheduler(
                job, spec.poll.interval,
                max_iterations=max_iterations, jitter_seconds=spec.poll.jitter)))

    if spec.draft:
        job = DraftJob(db, make_writer(), persona, limit=spec.draft.limit)
        entries.append(SupervisedJob("draft", job, IntervalScheduler(
            job, spec.draft.interval,
            max_iterations=max_iterations, jitter_seconds=spec.draft.jitter)))

    if spec.publish:
        job = PublishJob(db, persona, limit=spec.publish.limit)
        entries.append(SupervisedJob("publish", job, WindowedScheduler(
            job, spec.publish.interval, windows=spec.publish.windows, tz=spec.publish.tz,
            max_iterations=max_iterations, jitter_seconds=spec.publish.jitter)))

    if spec.engage:
        job = EngageJob(db, persona, EngagePolicy.from_spec(spec.engage),
                        limit=spec.engage.limit)
        entries.append(SupervisedJob("engage", job, WindowedScheduler(
            job, spec.engage.interval, windows=spec.engage.windows, tz=spec.engage.tz,
            max_iterations=max_iterations, jitter_seconds=spec.engage.jitter)))

    if spec.metrics:
        job = MetricsJob(db, make_engagement_source("bluesky"),
                         handle=persona.channel_handle("bluesky"),
                         post_limit=spec.metrics.post_limit)
        entries.append(SupervisedJob("metrics", job, IntervalScheduler(
            job, spec.metrics.interval,
            max_iterations=max_iterations, jitter_seconds=spec.metrics.jitter)))

    # Retention is not opt-in: each persona's DB gets its daily prune.
    prune = PruneJob(db)
    entries.append(SupervisedJob("prune", prune, IntervalScheduler(
        prune, config.PRUNE_INTERVAL_SECONDS, max_iterations=max_iterations)))

    return entries


def supervise(
    persona: Persona, db: Database, *, max_iterations: int = 0,
    stop: threading.Event | None = None,
) -> None:
    """Run all of the persona's jobs until stop is set (or every scheduler hits max_iterations)."""
    stop = stop or threading.Event()
    kalshi_client = KalshiClient() if persona.pipeline.poll else None
    try:
        entries = build_supervised(persona, db, kalshi_client=kalshi_client,
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
        if kalshi_client is not None:
            kalshi_client.close()
