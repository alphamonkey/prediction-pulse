"""Pure active-hours window helpers (the 'when' for dayparting).

Windows are local-time `("HH:MM", "HH:MM")` pairs in a named tz (DST-correct via `zoneinfo`); a
window with end <= start wraps midnight. Empty windows = always active (no dayparting). These are
pure functions over an injected `now`, so the WindowedScheduler stays trivially testable.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from zoneinfo import ZoneInfo

Window = tuple[str, str]


def _sec(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 3600 + int(m) * 60


def _seconds_of_day(local: dt.datetime) -> int:
    return local.hour * 3600 + local.minute * 60 + local.second


def within_window(now: dt.datetime, windows: Sequence[Window], tz: str) -> bool:
    """True if `now` (tz-aware) falls inside any active window. Empty windows = always active."""
    if not windows:
        return True
    cur = _seconds_of_day(now.astimezone(ZoneInfo(tz)))
    for start, end in windows:
        s, e = _sec(start), _sec(end)
        if s <= e:
            if s <= cur < e:
                return True
        elif cur >= s or cur < e:  # wraps midnight
            return True
    return False


def seconds_until_next_window(now: dt.datetime, windows: Sequence[Window], tz: str) -> float:
    """Seconds until the next window opens; 0.0 if currently inside one (or no windows).

    Day-length is approximated as 86400s across the wrap to tomorrow — fine because the scheduler
    caps each sleep and re-evaluates, so any DST-day imprecision self-corrects.
    """
    if not windows or within_window(now, windows, tz):
        return 0.0
    cur = _seconds_of_day(now.astimezone(ZoneInfo(tz)))
    starts = sorted(_sec(start) for start, _ in windows)
    for st in starts:
        if st > cur:
            return float(st - cur)
    return float(86400 - cur + starts[0])
