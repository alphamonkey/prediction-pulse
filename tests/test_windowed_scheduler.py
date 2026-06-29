"""Chunk 2: WindowedScheduler — interval cadence inside windows, skip/sleep outside."""

from __future__ import annotations

import datetime as dt
import threading

import pytest

from pulse.scheduler.base import Scheduler
from pulse.scheduler.windowed import WindowedScheduler

TZ = "America/New_York"
W = (("07:00", "10:00"), ("12:00", "14:00"), ("17:00", "22:00"))
IN = dt.datetime(2026, 7, 6, 13, 30, tzinfo=dt.timezone.utc)   # 09:30 EDT — inside
OUT = dt.datetime(2026, 7, 6, 6, 0, tzinfo=dt.timezone.utc)    # 02:00 EDT — dead hours


class FakeJob:
    name = "fake"

    def __init__(self, on_run=None, raise_=False):
        self.runs = 0
        self._on_run = on_run
        self._raise = raise_

    def run(self):
        self.runs += 1
        if self._on_run:
            self._on_run()
        if self._raise:
            raise RuntimeError("boom")
        return None


def _sched(job, *, clock, max_iterations=0, idle_cap_seconds=0):
    return WindowedScheduler(job, 0, windows=W, tz=TZ, max_iterations=max_iterations,
                             jitter_seconds=0, idle_cap_seconds=idle_cap_seconds, clock=clock)


def test_is_a_scheduler():
    assert isinstance(_sched(FakeJob(), clock=lambda: IN), Scheduler)


def test_runs_job_inside_window():
    job = FakeJob()
    _sched(job, clock=lambda: IN, max_iterations=2).run(threading.Event())
    assert job.runs == 2


def test_skips_job_outside_window():
    stop = threading.Event()
    job = FakeJob()

    def clock():
        stop.set()  # end the loop after this pass
        return OUT

    _sched(job, clock=clock).run(stop)
    assert job.runs == 0


def test_stop_event_halts_loop_even_when_unlimited():
    stop = threading.Event()
    job = FakeJob(on_run=lambda: stop.set())  # stop after first run
    _sched(job, clock=lambda: IN).run(stop)   # max_iterations=0 (unlimited)
    assert job.runs == 1


def test_survives_a_failing_cycle():
    job = FakeJob(raise_=True)
    _sched(job, clock=lambda: IN, max_iterations=2).run(threading.Event())  # must not raise
    assert job.runs == 2
