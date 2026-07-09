"""GeneratorSource — the no-external-input ContentSource.

Emits operator-authored topic seeds as Events; the writer (the one LLM seam) phrases them
in the persona's voice, so this source never calls a model and needs no credentials.
Idempotency is bucket-stable: dedup keys derive purely from the time bucket and topic, so
re-polls and process restarts within a bucket emit nothing new, and topics rotate
deterministically across buckets.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pulse.models import Event
from pulse.store.db import Database

DEFAULT_TOPIC = "Write one post in your voice."

_DURATION = re.compile(r"^(\d+)([mhd])$")
_UNIT_SECONDS = {"m": 60, "h": 3600, "d": 86400}


def _parse_bucket(bucket: str) -> int:
    match = _DURATION.match(bucket)
    if not match:
        raise ValueError(f"generator bucket {bucket!r} must look like '30m', '4h' or '1d'")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def _slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-") or "topic"


class GeneratorSource:
    venue = "generator"

    def __init__(self, *, topics: list[str] | None = None, count: int = 1,
                 bucket: str = "1d") -> None:
        self._topics = list(topics) if topics else [DEFAULT_TOPIC]
        self._count = min(count, len(self._topics))  # one event per topic per bucket, max
        self._bucket_seconds = _parse_bucket(bucket)

    def fetch_events(self, db: Database, now: datetime) -> list[Event]:
        bucket_index = int(now.timestamp()) // self._bucket_seconds
        bucket_start = datetime.fromtimestamp(
            bucket_index * self._bucket_seconds, tz=timezone.utc)
        stamp = bucket_start.isoformat(timespec="minutes")

        events = []
        start = (bucket_index * self._count) % len(self._topics)
        for j in range(self._count):
            topic = self._topics[(start + j) % len(self._topics)]
            slug = _slug(topic)
            events.append(Event(
                rule="generated",
                venue=self.venue,
                market_id=slug,
                ts=now,
                value_kind=None,
                from_value=None,
                to_value=None,
                magnitude=1.0,
                direction=None,
                headline=topic,
                dedup_key=f"generated:{slug}:{stamp}",
                context={"source_kind": "generated"},
            ))
        # ContentSource contract: record, return only the new ones (store backstops races).
        return [e for e in events if db.record_posted(e)]
