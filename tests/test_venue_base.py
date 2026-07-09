from datetime import datetime, timedelta, timezone

import pytest

from pulse import config
from pulse.models import Snapshot, ValueKind
from pulse.store.db import Database
from pulse.venue.base import ContentSource, SnapshotContentSource, SnapshotSource

_T = datetime(2026, 6, 24, 0, 0, 0, tzinfo=timezone.utc)


def test_config_universe_constants_are_sane():
    assert config.KALSHI_API_HOST.startswith("https://")
    assert len(config.PULSE_CATEGORIES) > 0
    # The forbidden topics must never be in the allowlist.
    lowered = {c.lower() for c in config.PULSE_CATEGORIES}
    assert not any("food" in c or "agricult" in c for c in lowered)
    assert config.MIN_MARKET_VOLUME_24H > 0
    assert config.HTTP_MAX_RETRIES >= 0


def test_snapshot_source_is_runtime_checkable():
    class Dummy:
        venue = "dummy"

        def fetch_snapshots(self, now):
            return []

    assert isinstance(Dummy(), SnapshotSource)
    assert not isinstance(object(), SnapshotSource)


def test_content_source_is_runtime_checkable():
    class Dummy:
        venue = "dummy"

        def fetch_events(self, db, now):
            return []

    assert isinstance(Dummy(), ContentSource)
    assert not isinstance(object(), ContentSource)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


class _FixedSnapshots:
    venue = "kalshi"

    def __init__(self, snapshots):
        self._snapshots = snapshots

    def fetch_snapshots(self, now):
        return self._snapshots


def _swing_snaps():
    # +15pts, crosses no milestone level -> isolates odds_swing.
    return [
        Snapshot("kalshi", "A", _T, 0.55, ValueKind.PROBABILITY),
        Snapshot("kalshi", "A", _T + timedelta(minutes=10), 0.70, ValueKind.PROBABILITY),
    ]


def test_snapshot_adapter_stores_and_emits_recorded_events(db):
    adapter = SnapshotContentSource(_FixedSnapshots(_swing_snaps()))
    assert adapter.venue == "kalshi"
    events = adapter.fetch_events(db, _T + timedelta(minutes=10))
    assert [e.rule for e in events] == ["odds_swing"]
    # Snapshots hit the store and the event is in the idempotency log.
    assert len(db.get_recent_snapshots("kalshi", "A")) == 2
    assert db.has_posted(events[0].dedup_key)


def test_snapshot_adapter_is_idempotent_on_repeat(db):
    adapter = SnapshotContentSource(_FixedSnapshots(_swing_snaps()))
    adapter.fetch_events(db, _T + timedelta(minutes=10))
    assert adapter.fetch_events(db, _T + timedelta(minutes=10)) == []
