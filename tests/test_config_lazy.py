"""Env-derived config is read lazily (at call time), never bound at import.

Import-time binding breaks per-persona env loading (secrets/<name>.env is loaded at runtime,
after `pulse.config` has long been imported) — and it already made test_defaults_to_dryrun
rot the moment the real .env went live. These accessors must reflect the environment *now*.
"""

from __future__ import annotations

from pulse import config


def test_pulse_mode_reflects_env_set_after_import(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "live")
    assert config.pulse_mode() == "live"


def test_pulse_mode_defaults_to_dryrun_when_unset(monkeypatch):
    monkeypatch.delenv("PULSE_MODE", raising=False)
    assert config.pulse_mode() == "dryrun"


def test_pulse_mode_is_lowercased(monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "LIVE")
    assert config.pulse_mode() == "live"


def test_bluesky_creds_reflect_env(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "someone.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "hunter2")
    assert config.bluesky_handle() == "someone.bsky.social"
    assert config.bluesky_app_password() == "hunter2"


def test_bluesky_creds_default_empty(monkeypatch):
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    assert config.bluesky_handle() == ""
    assert config.bluesky_app_password() == ""


def test_anthropic_api_key_reflects_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert config.anthropic_api_key() == "sk-test"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert config.anthropic_api_key() == ""


def test_db_path_reflects_env(monkeypatch):
    monkeypatch.setenv("PULSE_DB_PATH", "/tmp/elsewhere.db")
    assert config.db_path() == "/tmp/elsewhere.db"


def test_db_path_default(monkeypatch):
    monkeypatch.delenv("PULSE_DB_PATH", raising=False)
    assert config.db_path() == "prediction_pulse.db"


def test_db_path_for_persona(monkeypatch):
    monkeypatch.delenv("PULSE_DB_PATH", raising=False)
    monkeypatch.delenv("PULSE_DATA_DIR", raising=False)
    assert config.db_path_for("gnome") == "data/gnome.db"


def test_db_path_for_respects_data_dir(monkeypatch):
    monkeypatch.delenv("PULSE_DB_PATH", raising=False)
    monkeypatch.setenv("PULSE_DATA_DIR", "/var/lib/pulse")
    assert config.db_path_for("gnome") == "/var/lib/pulse/gnome.db"


def test_db_path_for_escape_hatch_wins(monkeypatch):
    # PULSE_DB_PATH pins every persona to one file (transition / tests / recovery).
    monkeypatch.setenv("PULSE_DB_PATH", "/tmp/one.db")
    assert config.db_path_for("gnome") == "/tmp/one.db"
