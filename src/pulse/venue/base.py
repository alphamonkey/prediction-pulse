"""The venue-agnostic seam: a source yields normalized Snapshots for one venue."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from pulse.models import Snapshot


@runtime_checkable
class SnapshotSource(Protocol):
    venue: str

    def fetch_snapshots(self, now: datetime) -> list[Snapshot]:
        """Return current normalized snapshots for this venue, timestamped `now`."""
        ...
