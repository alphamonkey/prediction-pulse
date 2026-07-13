"""CLI entry point.

`pulse supervise <name>` runs EVERYTHING the persona's [pipeline] declares in one process.
`pulse poll`  runs one detect cycle against live Kalshi data (dryrun).
`pulse run`   drives the same cycle on a cadence (dryrun), until stopped.
`pulse draft` writes post drafts for the top recent events in a persona's voice (dryrun);
              with `--interval N` it drafts on a cadence until stopped.
`pulse publish` posts a persona's freshest drafts to its channels (Bluesky) — dryrun until
                PULSE_MODE=live; `--interval N` runs it on a cadence.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import signal
import threading
from pathlib import Path

from dotenv import load_dotenv

from pulse import config
from pulse.drafter import DraftJob, draft_once
from pulse.engage.base import SignalKind
from pulse.engager import EngageJob, EngagePolicy
from pulse.metrics.collect import MetricsJob
from pulse.metrics.factory import make_engagement_source
from pulse.persona import load_persona
from pulse.pipeline import SourceSpec
from pulse.poller import PollJob
from pulse.pruner import PruneJob
from pulse.publisher import PublishJob
from pulse.scheduler.interval import IntervalScheduler
from pulse.scheduler.windowed import WindowedScheduler
from pulse.store.db import Database
from pulse.supervisor import supervise
from pulse.venue.kalshi import KalshiClient
from pulse.venue.registry import SourceContext, make_source
from pulse.writer.factory import make_writer

log = logging.getLogger("pulse")


def _open_db(persona_name: str) -> Database:
    """Open (creating if needed) the persona's own DB under the data dir."""
    path = config.db_path_for(persona_name)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    db.connect()
    return db


@contextlib.contextmanager
def _poll_job(source_name: str, persona_name: str):
    db = _open_db(persona_name)
    try:
        # Lazy: only market-source builders materialize the Kalshi client.
        ctx = SourceContext(kalshi_factory=lambda: KalshiClient())
        try:
            yield PollJob(make_source(SourceSpec(source_name), ctx), db)
        finally:
            ctx.close()
    finally:
        db.close()


def _run_poll(source_name: str, persona_name: str) -> None:
    with _poll_job(source_name, persona_name) as job:
        job.run()


def _install_stop() -> threading.Event:
    """A stop Event wired to graceful SIGINT/SIGTERM shutdown."""
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    return stop


def _run_scheduled(job, interval: int, max_iterations: int, jitter: int = 0) -> None:
    """Drive any Job on a fixed cadence (24/7)."""
    IntervalScheduler(
        job, interval, max_iterations=max_iterations, jitter_seconds=jitter
    ).run(_install_stop())


def _run_windowed(job, interval: int, windows, tz: str, max_iterations: int, jitter: int) -> None:
    """Drive an outward-action Job on a cadence, but only inside active windows (dayparting)."""
    WindowedScheduler(
        job, interval, windows=windows, tz=tz, max_iterations=max_iterations, jitter_seconds=jitter
    ).run(_install_stop())


def _run_loop(interval: int, max_iterations: int, jitter: int, source_name: str,
              persona_name: str) -> None:
    with _poll_job(source_name, persona_name) as job:
        _run_scheduled(job, interval, max_iterations, jitter)


def _run_publish(limit: int, persona_name: str, interval: int, max_iterations: int,
                 jitter: int) -> None:
    persona = load_persona(persona_name)
    db = _open_db(persona_name)
    try:
        job = PublishJob(db, persona, limit=limit)
        if interval > 0:
            log.info("publishing every %ds within windows (persona=%s, mode=%s)",
                     interval, persona.name, config.pulse_mode())
            _run_windowed(job, interval, config.PUBLISH_WINDOWS, config.ACTIVE_TZ,
                          max_iterations, jitter)
        else:
            job.run()
    finally:
        db.close()


def _run_metrics(post_limit: int, persona_name: str, interval: int, max_iterations: int,
                 jitter: int) -> None:
    persona = load_persona(persona_name)
    db = _open_db(persona_name)
    try:
        source = make_engagement_source("bluesky")
        job = MetricsJob(db, source, handle=persona.channel_handle("bluesky"),
                         post_limit=post_limit)
        if interval > 0:
            log.info("collecting metrics every %ds (platform=%s, mode=%s)",
                     interval, source.name, config.pulse_mode())
            _run_scheduled(job, interval, max_iterations, jitter)
        else:
            job.run()
    finally:
        db.close()


def _engage_policy() -> EngagePolicy:
    """Build the engagement policy from config (relevance/safety + enabled actions + caps)."""
    caps = {
        SignalKind.LIKE: config.MAX_LIKES_PER_DAY,
        SignalKind.REPOST: config.MAX_REPOSTS_PER_DAY,
        SignalKind.FOLLOW: config.MAX_FOLLOWS_PER_DAY,
    }
    actions = tuple(SignalKind(a) for a in config.ENGAGE_ACTIONS)
    return EngagePolicy(
        allow=list(config.ENGAGE_ALLOW),
        deny=list(config.ENGAGE_DENY),
        actions=actions,
        caps=caps,
        queries=list(config.ENGAGE_QUERIES),
    )


def _run_engage(limit: int, persona_name: str, interval: int, max_iterations: int,
                jitter: int) -> None:
    # NB: persona/policy are loaded once at startup (same as draft/publish) — GitHub issue #13
    # tracks moving persona reload per-cycle across all the long-running jobs.
    persona = load_persona(persona_name)
    policy = _engage_policy()
    db = _open_db(persona_name)
    try:
        job = EngageJob(db, persona, policy, limit=limit)
        if interval > 0:
            log.info("engaging every %ds within windows (persona=%s, mode=%s)",
                     interval, persona.name, config.pulse_mode())
            _run_windowed(job, interval, config.ENGAGE_WINDOWS, config.ACTIVE_TZ,
                          max_iterations, jitter)
        else:
            job.run()
    finally:
        db.close()


def _run_prune(retention_days: int, persona_name: str) -> None:
    db = _open_db(persona_name)
    try:
        PruneJob(db, retention_days=retention_days).run()
    finally:
        db.close()


def _run_vacuum(persona_name: str) -> None:
    """One-time compaction of the on-disk file. Stop the writer services first (needs EXCLUSIVE)."""
    import os

    def _mb(path: str) -> float:
        return os.path.getsize(path) / 1e6 if os.path.exists(path) else 0.0

    path = config.db_path_for(persona_name)
    db = Database(path)
    db.connect()
    try:
        before = _mb(path)
        log.info("vacuum: compacting %s (%.1f MB) — needs an exclusive lock", path, before)
        db.vacuum()
        log.info("vacuum complete: %.1f MB -> %.1f MB", before, _mb(path))
    finally:
        db.close()


def _run_supervise(persona_name: str, max_iterations: int) -> None:
    """Run the persona's whole declared stack in this process (the pulse@<name> service body)."""
    # Per-persona secrets win over the repo-level .env loaded at config import — under systemd
    # the same file arrives via EnvironmentFile=, so override=True is a no-op there.
    secrets = Path(config.SECRETS_DIR) / f"{persona_name}.env"
    if secrets.exists():
        load_dotenv(secrets, override=True)
        log.info("loaded secrets from %s", secrets)
    persona = load_persona(persona_name)
    # The supervisor opens one connection per job itself (WAL serializes across them) —
    # main just ensures the data dir exists and hands over the path.
    path = config.db_path_for(persona_name)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    supervise(persona, path, max_iterations=max_iterations, stop=_install_stop())


def _run_draft(limit: int, persona_name: str, interval: int, max_iterations: int,
               jitter: int) -> None:
    persona = load_persona(persona_name)
    writer = make_writer()
    db = _open_db(persona_name)
    try:
        if interval > 0:
            log.info("drafting every %ds (persona=%s, writer=%s, mode=%s)",
                     interval, persona.name, writer.name, config.pulse_mode())
            _run_scheduled(DraftJob(db, writer, persona, limit=limit), interval, max_iterations,
                           jitter)
        else:
            report = draft_once(db, writer, persona, limit=limit)
            log.info(
                "draft complete (mode=%s, persona=%s, writer=%s): %d candidates, %d new drafts",
                config.pulse_mode(), persona.name, writer.name, report.candidates, report.drafted,
            )
    finally:
        db.close()


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pulse")
    sub = parser.add_subparsers(dest="command", required=True)
    sup_p = sub.add_parser("supervise",
                           help="Run ALL jobs a persona's [pipeline] declares, in one process.")
    sup_p.add_argument("persona", help="Persona name under personas/.")
    sup_p.add_argument("--max-iterations", type=int, default=0,
                       help="Stop each job after N cycles; 0 = run until stopped (default: 0).")
    poll_p = sub.add_parser("poll", help="Run one poll+detect cycle and exit (no publish).")
    poll_p.add_argument("--source", choices=("kalshi", "trend"), default="kalshi",
                        help="Market selection: broad allowlist (kalshi) or Bluesky-trend-selected (trend).")
    poll_p.add_argument("--persona", default=config.PERSONA,
                        help="Whose DB the snapshots land in (default: %(default)s).")
    run_p = sub.add_parser("run", help="Poll+detect on a cadence until stopped (no publish).")
    run_p.add_argument("--source", choices=("kalshi", "trend"), default="kalshi",
                       help="Market selection: broad allowlist (kalshi) or Bluesky-trend-selected (trend).")
    run_p.add_argument("--persona", default=config.PERSONA,
                       help="Whose DB the snapshots land in (default: %(default)s).")
    run_p.add_argument("--interval", type=int, default=config.DEFAULT_INTERVAL_SECONDS,
                       help="Seconds between cycles (default: %(default)s).")
    run_p.add_argument("--max-iterations", type=int, default=0,
                       help="Stop after N cycles; 0 = unlimited (default: 0).")
    run_p.add_argument("--jitter", type=int, default=0,
                       help="Max extra random seconds added to each interval (default: 0).")
    draft_p = sub.add_parser("draft", help="Write post drafts for top recent events (no publish).")
    draft_p.add_argument("--limit", type=int, default=config.DRAFTS_PER_RUN,
                         help="Max events to draft this run (default: %(default)s).")
    draft_p.add_argument("--persona", default=config.PERSONA,
                         help="Persona name under personas/ (default: %(default)s).")
    draft_p.add_argument("--interval", type=int, default=0,
                         help="Run on a cadence (seconds); 0 = one-shot (default: 0).")
    draft_p.add_argument("--max-iterations", type=int, default=0,
                         help="With --interval, stop after N cycles; 0 = unlimited (default: 0).")
    draft_p.add_argument("--jitter", type=int, default=0,
                         help="Max extra random seconds added to each interval (default: 0).")
    pub_p = sub.add_parser("publish", help="Post a persona's freshest drafts to its channels.")
    pub_p.add_argument("--persona", default=config.PERSONA,
                       help="Persona name under personas/ (default: %(default)s).")
    pub_p.add_argument("--limit", type=int, default=config.POSTS_PER_CYCLE,
                       help="Max posts per cycle (also capped by the daily limit; default: %(default)s).")
    pub_p.add_argument("--interval", type=int, default=0,
                       help="Run on a cadence (seconds); 0 = one-shot (default: 0).")
    pub_p.add_argument("--max-iterations", type=int, default=0,
                       help="With --interval, stop after N cycles; 0 = unlimited (default: 0).")
    pub_p.add_argument("--jitter", type=int, default=0,
                       help="Max extra random seconds added to each interval (default: 0).")
    eng_p = sub.add_parser("engage", help="Take engagement signals (like/repost/follow) on relevant content.")
    eng_p.add_argument("--persona", default=config.PERSONA,
                       help="Persona name under personas/ (default: %(default)s).")
    eng_p.add_argument("--limit", type=int, default=config.ENGAGE_TARGETS_PER_RUN,
                       help="Candidate targets to pull per cycle (default: %(default)s).")
    eng_p.add_argument("--interval", type=int, default=0,
                       help="Run on a cadence (seconds); 0 = one-shot (default: 0).")
    eng_p.add_argument("--max-iterations", type=int, default=0,
                       help="With --interval, stop after N cycles; 0 = unlimited (default: 0).")
    eng_p.add_argument("--jitter", type=int, default=0,
                       help="Max extra random seconds added to each interval (default: 0).")
    met_p = sub.add_parser("metrics", help="Collect engagement back from the platform for the dashboard.")
    met_p.add_argument("--persona", default=config.PERSONA,
                       help="Persona name under personas/ (default: %(default)s).")
    met_p.add_argument("--limit", type=int, default=config.METRICS_POST_WINDOW,
                       help="Recent posts to refresh engagement for (default: %(default)s).")
    met_p.add_argument("--interval", type=int, default=0,
                       help="Run on a cadence (seconds); 0 = one-shot (default: 0).")
    met_p.add_argument("--max-iterations", type=int, default=0,
                       help="With --interval, stop after N cycles; 0 = unlimited (default: 0).")
    met_p.add_argument("--jitter", type=int, default=0,
                       help="Max extra random seconds added to each interval (default: 0).")
    prune_p = sub.add_parser("prune", help="Delete market snapshots older than the retention horizon and reclaim space.")
    prune_p.add_argument("--retention-days", type=int, default=config.SNAPSHOT_RETENTION_DAYS,
                         help="Keep snapshots newer than this many days (default: %(default)s).")
    prune_p.add_argument("--persona", default=config.PERSONA,
                         help="Whose DB to prune (default: %(default)s).")
    vac_p = sub.add_parser("vacuum", help="One-time: compact the DB file + convert to incremental auto_vacuum (stop writers first).")
    vac_p.add_argument("--persona", default=config.PERSONA,
                       help="Whose DB to compact (default: %(default)s).")
    serve_p = sub.add_parser("serve", help="Run the read-only monitoring dashboard.")
    serve_p.add_argument("--host", default=config.DASHBOARD_HOST,
                         help="Bind host (default: %(default)s).")
    serve_p.add_argument("--port", type=int, default=config.DASHBOARD_PORT,
                         help="Bind port (default: %(default)s).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "supervise":
        _run_supervise(args.persona, args.max_iterations)
    elif args.command == "poll":
        _run_poll(args.source, args.persona)
    elif args.command == "run":
        _run_loop(args.interval, args.max_iterations, args.jitter, args.source, args.persona)
    elif args.command == "draft":
        _run_draft(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "publish":
        _run_publish(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "engage":
        _run_engage(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "metrics":
        _run_metrics(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "prune":
        _run_prune(args.retention_days, args.persona)
    elif args.command == "vacuum":
        _run_vacuum(args.persona)
    elif args.command == "serve":
        from pulse.server.app import serve  # lazy: fastapi only needed for the dashboard
        log.info("dashboard on http://%s:%d", args.host, args.port)
        serve(args.host, args.port)
