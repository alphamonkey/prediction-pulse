from datetime import datetime, timezone

from pulse import config
from pulse.venue.base import SnapshotSource


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
