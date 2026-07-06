"""Smoke tests — the scaffold imports and config has safe defaults."""

import pulse
from pulse import config


def test_package_version():
    assert pulse.__version__ == "0.1.0"


def test_defaults_to_dryrun(monkeypatch):
    # Safe default: never publish until explicitly set to live.
    monkeypatch.delenv("PULSE_MODE", raising=False)
    assert config.pulse_mode() == "dryrun"


def test_detector_thresholds_are_sane():
    assert 0.0 < config.MIN_ODDS_MOVE < 1.0
    assert config.MIN_VOLUME_SPIKE > 1.0
    assert config.MAX_POSTS_PER_DAY > 0
