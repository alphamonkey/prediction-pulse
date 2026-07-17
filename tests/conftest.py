"""Shared test isolation: never let a test create the real data/ dir, touch a real DB, or spend
money."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PULSE_DATA_DIR", str(tmp_path / "data"))


@pytest.fixture(autouse=True)
def _no_paid_api_calls(monkeypatch):
    """config.load_dotenv() reads the repo's real .env at import, so a test that reaches
    make_writer() would otherwise construct a REAL ClaudeWriter and bill the live key. Unset it by
    default; a test that wants the Claude path sets it back explicitly (and injects a fake client).
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
