"""A dayparting Scheduler: run a Job on an interval, but only inside active windows.

The `when` for dayparting lives here in the Scheduler seam (not in the orchestrators) — so any Job
gets active-hours behaviour for free, and the scheduler can sleep toward the next window instead of
waking all night to no-op. Inside a window it behaves like `IntervalScheduler`; outside, it waits
until the next window opens (capped so `stop` stays responsive and DST drift self-corrects).
"""

from __future__ import annotations

import logging
import random
import threading
from collections.abc import Callable, Sequence

from pulse.models import _now
from pulse.scheduler.base import Job
from pulse.scheduler.windows import Window, seconds_until_next_window, within_window

log = logging.getLogger("pulse")

_IDLE_CAP_SECONDS = 900  # re-check at least every 15 min while idle (responsive stop + DST drift)


class WindowedScheduler:
    def __init__(
        self, job: Job, interval_seconds: int, *, windows: Sequence[Window], tz: str,
        max_iterations: int = 0, jitter_seconds: float = 0,
        idle_cap_seconds: float = _IDLE_CAP_SECONDS, clock: Callable[[], object] = _now,
    ) -> None:
        self._job = job
        self._interval = interval_seconds
        self._windows = windows
        self._tz = tz
        self._max_iterations = max_iterations
        self._jitter = jitter_seconds
        self._idle_cap = idle_cap_seconds
        self._clock = clock

    def run(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        log.info("scheduler: job '%s' every %ds within %d window(s) [%s]",
                 self._job.name, self._interval, len(self._windows), self._tz)
        n = 0
        while not stop.is_set():
            if self._max_iterations and n >= self._max_iterations:
                break
            now = self._clock()
            if within_window(now, self._windows, self._tz):
                n += 1
                try:
                    self._job.run()
                except Exception:  # noqa: BLE001 — one bad cycle must not kill the loop
                    log.exception("job '%s' cycle %d failed", self._job.name, n)
                stop.wait(self._interval + random.uniform(0, self._jitter))
            else:
                idle = min(seconds_until_next_window(now, self._windows, self._tz), self._idle_cap)
                stop.wait(idle)
        log.info("scheduler: stopped after %d cycle(s)", n)
