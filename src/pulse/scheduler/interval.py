"""A time-based Scheduler: run a Job on a fixed interval until stopped.

This is one implementation of the Scheduler seam. The sleep is interruptible — it waits on the
`stop` event rather than `time.sleep`, so a signal handler (or a test) can end it promptly. A job
raising is logged and the loop continues, so a transient error never halts collection.
"""

from __future__ import annotations

import logging
import threading

from pulse.scheduler.base import Job

log = logging.getLogger("pulse")


class IntervalScheduler:
    def __init__(self, job: Job, interval_seconds: int, *, max_iterations: int = 0) -> None:
        self._job = job
        self._interval = interval_seconds
        self._max_iterations = max_iterations  # 0 = unlimited

    def run(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        log.info("scheduler: running job '%s' every %ds", self._job.name, self._interval)
        n = 0
        while not stop.is_set():
            if self._max_iterations and n >= self._max_iterations:
                break
            n += 1
            try:
                self._job.run()
            except Exception:  # noqa: BLE001 — one bad cycle must not kill the loop
                log.exception("job '%s' cycle %d failed", self._job.name, n)
            stop.wait(self._interval)
        log.info("scheduler: stopped after %d cycle(s)", n)
