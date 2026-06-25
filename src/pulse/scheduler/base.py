"""The scheduler seam: decouple *what runs* (a Job) from *what decides when* (a Scheduler).

A Job is a named unit of work that knows nothing about timing (polling now; the writer and
publisher later). A Scheduler drives jobs — the interval loop is one implementation; an
event-driven (e.g. WebSocket) scheduler would be another, reusing the same Job. This mirrors
how SnapshotSource decoupled venues from the detector.
"""

from __future__ import annotations

import threading
from typing import Protocol, runtime_checkable


@runtime_checkable
class Job(Protocol):
    """A named unit of work, invoked by a Scheduler. Timing-agnostic."""

    name: str

    def run(self) -> object:
        """Do one unit of work, returning an optional report."""
        ...


@runtime_checkable
class Scheduler(Protocol):
    """Decides when to invoke its job(s), running until `stop` is set."""

    def run(self, stop: threading.Event | None = None) -> None:
        ...
