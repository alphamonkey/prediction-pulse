"""CLI entry point.

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

from pulse import config
from pulse.drafter import DraftJob, draft_once
from pulse.engage.base import SignalKind
from pulse.engager import EngageJob, EngagePolicy
from pulse.metrics.collect import MetricsJob
from pulse.metrics.factory import make_engagement_source
from pulse.persona import load_persona
from pulse.poller import PollJob
from pulse.publisher import PublishJob
from pulse.scheduler.interval import IntervalScheduler
from pulse.scheduler.windowed import WindowedScheduler
from pulse.store.db import Database
from pulse.venue.kalshi import KalshiClient, KalshiSource
from pulse.venue.trending import BlueskyTrendClient, BlueskyTrendSource
from pulse.writer.base import Writer
from pulse.writer.claude import ClaudeWriter
from pulse.writer.template import TemplateWriter

log = logging.getLogger("pulse")


def _make_source(source_name: str, kalshi_client: KalshiClient):
    """The broad category-allowlist source, or the Bluesky-trend-selected peer. Both yield
    `venue="kalshi"` snapshots, so the store + detector are unchanged either way."""
    if source_name == "trend":
        return BlueskyTrendSource(
            BlueskyTrendClient(config.BLUESKY_HANDLE, config.BLUESKY_APP_PASSWORD), kalshi_client)
    return KalshiSource(kalshi_client)


@contextlib.contextmanager
def _poll_job(source_name: str = "kalshi"):
    db = Database(config.DB_PATH)
    db.connect()
    try:
        client = KalshiClient()
        try:
            yield PollJob(_make_source(source_name, client), db)
        finally:
            client.close()
    finally:
        db.close()


def _run_poll(source_name: str = "kalshi") -> None:
    with _poll_job(source_name) as job:
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


def _run_loop(interval: int, max_iterations: int, jitter: int, source_name: str = "kalshi") -> None:
    with _poll_job(source_name) as job:
        _run_scheduled(job, interval, max_iterations, jitter)


def _run_publish(limit: int, persona_name: str, interval: int, max_iterations: int,
                 jitter: int) -> None:
    persona = load_persona(persona_name)
    db = Database(config.DB_PATH)
    db.connect()
    try:
        job = PublishJob(db, persona, limit=limit)
        if interval > 0:
            log.info("publishing every %ds within windows (persona=%s, mode=%s)",
                     interval, persona.name, config.PULSE_MODE)
            _run_windowed(job, interval, config.PUBLISH_WINDOWS, config.ACTIVE_TZ,
                          max_iterations, jitter)
        else:
            job.run()
    finally:
        db.close()


def _run_metrics(post_limit: int, interval: int, max_iterations: int, jitter: int) -> None:
    db = Database(config.DB_PATH)
    db.connect()
    try:
        source = make_engagement_source("bluesky")
        job = MetricsJob(db, source, handle=config.BLUESKY_HANDLE, post_limit=post_limit)
        if interval > 0:
            log.info("collecting metrics every %ds (platform=%s, mode=%s)",
                     interval, source.name, config.PULSE_MODE)
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
    db = Database(config.DB_PATH)
    db.connect()
    try:
        job = EngageJob(db, persona, policy, limit=limit)
        if interval > 0:
            log.info("engaging every %ds within windows (persona=%s, mode=%s)",
                     interval, persona.name, config.PULSE_MODE)
            _run_windowed(job, interval, config.ENGAGE_WINDOWS, config.ACTIVE_TZ,
                          max_iterations, jitter)
        else:
            job.run()
    finally:
        db.close()


def make_writer() -> Writer:
    """ClaudeWriter when an API key is configured; the zero-cost template writer otherwise."""
    if config.ANTHROPIC_API_KEY:
        return ClaudeWriter()
    log.warning("ANTHROPIC_API_KEY not set — using the template writer (no LLM).")
    return TemplateWriter()


def _run_draft(limit: int, persona_name: str, interval: int, max_iterations: int,
               jitter: int) -> None:
    persona = load_persona(persona_name)
    writer = make_writer()
    db = Database(config.DB_PATH)
    db.connect()
    try:
        if interval > 0:
            log.info("drafting every %ds (persona=%s, writer=%s, mode=%s)",
                     interval, persona.name, writer.name, config.PULSE_MODE)
            _run_scheduled(DraftJob(db, writer, persona, limit=limit), interval, max_iterations,
                           jitter)
        else:
            report = draft_once(db, writer, persona, limit=limit)
            log.info(
                "draft complete (mode=%s, persona=%s, writer=%s): %d candidates, %d new drafts",
                config.PULSE_MODE, persona.name, writer.name, report.candidates, report.drafted,
            )
    finally:
        db.close()


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pulse")
    sub = parser.add_subparsers(dest="command", required=True)
    poll_p = sub.add_parser("poll", help="Run one poll+detect cycle and exit (no publish).")
    poll_p.add_argument("--source", choices=("kalshi", "trend"), default="kalshi",
                        help="Market selection: broad allowlist (kalshi) or Bluesky-trend-selected (trend).")
    run_p = sub.add_parser("run", help="Poll+detect on a cadence until stopped (no publish).")
    run_p.add_argument("--source", choices=("kalshi", "trend"), default="kalshi",
                       help="Market selection: broad allowlist (kalshi) or Bluesky-trend-selected (trend).")
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
    pub_p.add_argument("--limit", type=int, default=config.MAX_POSTS_PER_DAY,
                       help="Max posts this run (also capped by the daily limit; default: %(default)s).")
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
    met_p.add_argument("--limit", type=int, default=config.METRICS_POST_WINDOW,
                       help="Recent posts to refresh engagement for (default: %(default)s).")
    met_p.add_argument("--interval", type=int, default=0,
                       help="Run on a cadence (seconds); 0 = one-shot (default: 0).")
    met_p.add_argument("--max-iterations", type=int, default=0,
                       help="With --interval, stop after N cycles; 0 = unlimited (default: 0).")
    met_p.add_argument("--jitter", type=int, default=0,
                       help="Max extra random seconds added to each interval (default: 0).")
    serve_p = sub.add_parser("serve", help="Run the read-only monitoring dashboard.")
    serve_p.add_argument("--host", default=config.DASHBOARD_HOST,
                         help="Bind host (default: %(default)s).")
    serve_p.add_argument("--port", type=int, default=config.DASHBOARD_PORT,
                         help="Bind port (default: %(default)s).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "poll":
        _run_poll(args.source)
    elif args.command == "run":
        _run_loop(args.interval, args.max_iterations, args.jitter, args.source)
    elif args.command == "draft":
        _run_draft(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "publish":
        _run_publish(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "engage":
        _run_engage(args.limit, args.persona, args.interval, args.max_iterations, args.jitter)
    elif args.command == "metrics":
        _run_metrics(args.limit, args.interval, args.max_iterations, args.jitter)
    elif args.command == "serve":
        from pulse.server.app import serve  # lazy: fastapi only needed for the dashboard
        log.info("dashboard on http://%s:%d", args.host, args.port)
        serve(args.host, args.port)
