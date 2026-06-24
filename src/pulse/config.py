"""Central configuration — all tunable parameters in one place.

Credentials and mode come from the environment (.env, never committed).
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

# ── Mode ──
# Start in dry-run: detect events and draft posts, but DO NOT publish. Flip to "live" only
# after reviewing the generated copy.
PULSE_MODE = os.environ.get("PULSE_MODE", "dryrun").lower()  # "dryrun" | "live"

# ── Bluesky (atproto) ──
BLUESKY_HANDLE = os.environ.get("BLUESKY_HANDLE", "")
BLUESKY_APP_PASSWORD = os.environ.get("BLUESKY_APP_PASSWORD", "")

# ── Claude (post copy only — never the detector) ──
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
WRITER_MODEL = "claude-haiku-4-5-20251001"  # cheap; this is a language task, low volume

# ── Persistence ──
DB_PATH = os.environ.get("PULSE_DB_PATH", "prediction_pulse.db")

# ── Detector thresholds (starting points — tune from real data) ──
MIN_ODDS_MOVE = 0.10          # post when an event's probability moves >= 10 points
MIN_VOLUME_SPIKE = 3.0        # ... or volume spikes >= 3x its recent average

# ── Detector windows / baselines ──
ODDS_SWING_LOOKBACK_SECONDS = 6 * 3600   # window over which an odds move is measured
VOLUME_SPIKE_BASELINE_N = 5              # prior intervals defining "recent average"
MILESTONE_LEVELS = (0.25, 0.50, 0.75, 0.90)  # round probability levels worth a post
NEW_MARKET_MIN_VOLUME = 100.0            # cumulative-volume floor to flag a new market
NEW_MARKET_DEBUT_WINDOW = 6              # a market is "new" while it has <= this many snapshots
MAX_RECENT_SNAPSHOTS = 64                # cap loaded per market (INVARIANT: >> DEBUT_WINDOW)

# ── Cadence ──
MAX_POSTS_PER_DAY = 8         # rate cap so the feed stays signal, not spam

# ── Kalshi public API (read-only; no auth) ──
KALSHI_API_HOST = "https://api.elections.kalshi.com/trade-api/v2"

# ── Poller universe (allowlist + liquidity floor; tune from data) ──
# NB: agriculture/food categories are intentionally excluded per project rules.
PULSE_CATEGORIES = (
    "Politics",
    "Economics",
    "Companies",
    "Financials",
    "Science and Technology",
)
MIN_MARKET_VOLUME_24H = 1000.0   # contracts traded in the last 24h

# ── HTTP client resilience ──
HTTP_TIMEOUT_SECONDS = 10.0
HTTP_MAX_RETRIES = 3
