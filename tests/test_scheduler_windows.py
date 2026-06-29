"""Chunk 1: pure tz-aware active-window helpers."""

from __future__ import annotations

import datetime as dt

import pytest

from pulse.scheduler.windows import seconds_until_next_window, within_window

TZ = "America/New_York"
W = (("07:00", "10:00"), ("12:00", "14:00"), ("17:00", "22:00"))


def _utc(y, mo, d, h, mi=0):
    return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)


# ── within_window ──
def test_inside_a_window():
    # 13:30 UTC = 09:30 EDT (summer, UTC-4) -> inside 07:00-10:00
    assert within_window(_utc(2026, 7, 6, 13, 30), W, TZ) is True


def test_window_start_is_inclusive():
    # 16:00 UTC = 12:00 EDT -> exactly the lunch window start
    assert within_window(_utc(2026, 7, 6, 16, 0), W, TZ) is True


def test_window_end_is_exclusive():
    # 18:00 UTC = 14:00 EDT -> lunch window ends, not yet evening
    assert within_window(_utc(2026, 7, 6, 18, 0), W, TZ) is False


def test_outside_all_windows():
    # 06:00 UTC = 02:00 EDT -> dead hours
    assert within_window(_utc(2026, 7, 6, 6, 0), W, TZ) is False


def test_dst_aware_same_wall_clock_both_seasons():
    # Summer 13:30 UTC and winter 14:30 UTC both map to 09:30 local -> both inside
    assert within_window(_utc(2026, 7, 6, 13, 30), W, TZ) is True
    assert within_window(_utc(2026, 1, 6, 14, 30), W, TZ) is True


def test_empty_windows_is_always_active():
    assert within_window(_utc(2026, 7, 6, 6, 0), (), TZ) is True


def test_window_wrapping_midnight():
    wrap = (("22:00", "02:00"),)
    assert within_window(_utc(2026, 7, 7, 3, 0), wrap, TZ) is True    # 23:00 EDT
    assert within_window(_utc(2026, 7, 7, 5, 0), wrap, TZ) is True    # 01:00 EDT
    assert within_window(_utc(2026, 7, 7, 7, 0), wrap, TZ) is False   # 03:00 EDT


# ── seconds_until_next_window ──
def test_seconds_until_zero_when_inside():
    assert seconds_until_next_window(_utc(2026, 7, 6, 13, 30), W, TZ) == 0.0


def test_seconds_until_before_first_window():
    # 02:00 EDT -> next start 07:00 -> 5h
    assert seconds_until_next_window(_utc(2026, 7, 6, 6, 0), W, TZ) == 5 * 3600


def test_seconds_until_between_windows():
    # 14:30 EDT (18:30 UTC) -> next start 17:00 -> 2.5h
    assert seconds_until_next_window(_utc(2026, 7, 6, 18, 30), W, TZ) == 2.5 * 3600


def test_seconds_until_after_last_window_wraps_to_tomorrow():
    # 23:00 EDT (03:00 UTC next day) -> next start tomorrow 07:00 -> 8h
    assert seconds_until_next_window(_utc(2026, 7, 7, 3, 0), W, TZ) == 8 * 3600
