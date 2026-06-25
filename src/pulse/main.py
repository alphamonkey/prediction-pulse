"""CLI entry point.

`pulse poll` runs one detect cycle against live Kalshi data (dryrun).
`pulse run`  drives the same cycle on a cadence (dryrun), until stopped.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import signal
import threading

from pulse import config
from pulse.poller import PollJob
from pulse.scheduler.interval import IntervalScheduler
from pulse.store.db import Database
from pulse.venue.kalshi import KalshiClient, KalshiSource

log = logging.getLogger("pulse")


@contextlib.contextmanager
def _poll_job():
    """Open the db + Kalshi client, yield a PollJob, and close both on exit."""
    db = Database(config.DB_PATH)
    db.connect()
    try:
        client = KalshiClient()
        try:
            yield PollJob(KalshiSource(client), db)
        finally:
            client.close()
    finally:
        db.close()


def _run_poll() -> None:
    with _poll_job() as job:
        job.run()


def _run_loop(interval: int, max_iterations: int) -> None:
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    with _poll_job() as job:
        IntervalScheduler(job, interval, max_iterations=max_iterations).run(stop)


def cli(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="pulse")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("poll", help="Run one poll+detect cycle and exit (no publish).")
    run_p = sub.add_parser("run", help="Poll+detect on a cadence until stopped (no publish).")
    run_p.add_argument("--interval", type=int, default=config.DEFAULT_INTERVAL_SECONDS,
                       help="Seconds between cycles (default: %(default)s).")
    run_p.add_argument("--max-iterations", type=int, default=0,
                       help="Stop after N cycles; 0 = unlimited (default: 0).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "poll":
        _run_poll()
    elif args.command == "run":
        _run_loop(args.interval, args.max_iterations)
