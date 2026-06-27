"""Tests for the scheduler seam (Job + Scheduler protocols) and IntervalScheduler."""

import threading

from pulse.scheduler.base import Job, Scheduler
from pulse.scheduler.interval import IntervalScheduler


class CountingJob:
    """A Job that records how many times it ran (and can stop the scheduler)."""

    name = "counting"

    def __init__(self, stop_after=None, stop_event=None, raise_on=None):
        self.calls = 0
        self._stop_after = stop_after
        self._stop_event = stop_event
        self._raise_on = raise_on or set()

    def run(self):
        self.calls += 1
        if self.calls in self._raise_on:
            raise RuntimeError(f"boom on cycle {self.calls}")
        if self._stop_after is not None and self.calls >= self._stop_after:
            self._stop_event.set()
        return {"cycle": self.calls}


# ── seam ──

def test_job_is_runtime_checkable():
    assert isinstance(CountingJob(), Job)
    assert not isinstance(object(), Job)


def test_scheduler_protocol_is_runtime_checkable():
    class Dummy:
        def run(self, stop=None):
            return None

    assert isinstance(Dummy(), Scheduler)
    assert not isinstance(object(), Scheduler)


# ── IntervalScheduler ──

def test_interval_scheduler_is_a_scheduler():
    assert isinstance(IntervalScheduler(CountingJob(), interval_seconds=0), Scheduler)


def test_runs_exactly_max_iterations():
    job = CountingJob()
    # interval 0 -> stop.wait(0) returns immediately; max_iterations bounds the loop.
    IntervalScheduler(job, interval_seconds=0, max_iterations=3).run()
    assert job.calls == 3


def test_preset_stop_runs_zero_cycles():
    job = CountingJob()
    stop = threading.Event()
    stop.set()
    IntervalScheduler(job, interval_seconds=0).run(stop)
    assert job.calls == 0


def test_job_can_stop_the_loop():
    stop = threading.Event()
    job = CountingJob(stop_after=2, stop_event=stop)
    # unlimited iterations, but the job sets stop after its 2nd run
    IntervalScheduler(job, interval_seconds=0).run(stop)
    assert job.calls == 2


def test_loop_survives_job_exception_and_continues():
    job = CountingJob(raise_on={1})  # first cycle raises
    IntervalScheduler(job, interval_seconds=0, max_iterations=2).run()
    assert job.calls == 2  # did not propagate; ran the second cycle


def test_waits_on_the_provided_stop_event_between_cycles():
    """The interval is applied via stop.wait(interval) — not time.sleep."""
    waits = []

    class RecordingStop(threading.Event):
        def wait(self, timeout=None):
            waits.append(timeout)
            return super().wait(0)  # don't actually block

    job = CountingJob()
    IntervalScheduler(job, interval_seconds=7, max_iterations=2).run(RecordingStop())
    assert waits == [7, 7]  # one wait per completed cycle


def test_jitter_adds_random_offset_to_wait(monkeypatch):
    import pulse.scheduler.interval as interval_mod
    monkeypatch.setattr(interval_mod.random, "uniform", lambda a, b: 3.0)
    waits = []

    class RecordingStop(threading.Event):
        def wait(self, timeout=None):
            waits.append(timeout)
            return super().wait(0)

    IntervalScheduler(CountingJob(), interval_seconds=10, max_iterations=2,
                      jitter_seconds=5).run(RecordingStop())
    assert waits == [13, 13]  # interval 10 + jitter 3.0
