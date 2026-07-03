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
MAX_POSTS_PER_DAY = 9        # rate cap so the feed stays signal, not spam
DEFAULT_INTERVAL_SECONDS = 900  # `pulse run` poll cadence: 15 min

# ── Metrics collection (engagement pull-back for the KPM dashboard) ──
METRICS_INTERVAL_SECONDS = 3600  # `pulse metrics` cadence: 1 h
METRICS_POST_WINDOW = 50         # how many recent posts to refresh engagement for each cycle

# ── Dayparting (active-hours for OUTWARD actions: publish + engage) ──
# On Bluesky's reverse-chronological feed, when you act ≈ who sees it — so the publisher and engager
# only run inside these windows (poller/drafter/metrics stay 24/7). Local ("HH:MM","HH:MM") pairs in
# ACTIVE_TZ; end<=start wraps midnight; () = always-on. Tune from real audience-activity data.
ACTIVE_TZ = "America/New_York"   # US prediction-markets audience
PUBLISH_WINDOWS = (("07:00", "10:00"), ("12:00", "14:00"), ("17:00", "22:00"))  # ET peaks
ENGAGE_WINDOWS = PUBLISH_WINDOWS  # default same; set independently to run engagement broader/earlier

# ── Engagement (outbound signals: like/repost/follow relevant Bluesky content) ──
ENGAGE_INTERVAL_SECONDS = 3600   # `pulse engage` cadence: 1 h
ENGAGE_TARGETS_PER_RUN = 5       # candidates per cycle — small so signals drip within a window, not burst
# Bluesky search terms used to *find* targets:
ENGAGE_QUERIES = ("kalshi", "prediction market", "polymarket")
# Relevance filter — a target is kept only if its text matches one of these (defaults to the
# search terms; widen to engage adjacent conversations):
ENGAGE_ALLOW = ENGAGE_QUERIES
# Safety denylist — drop a target if its text contains any of these lightning-rod/toxic terms,
# even when on-topic. Deliberately over-rejects; tune per the persona's no-go rules.
ENGAGE_DENY = (
    "abortion", "shooting", "nazi", "racist", "racism", "rape",
    "genocide", "slur", "suicide", "porn",
)
# Which signals are enabled, attempted in this order. Follows are the most flag-prone, so they are
# OFF by default — add "follow" here (and watch MAX_FOLLOWS_PER_DAY) to enable.
ENGAGE_ACTIONS = ("like", "repost")
MAX_LIKES_PER_DAY = 30           # rolling-24h cap per action (keeps signals human-paced)
MAX_REPOSTS_PER_DAY = 5
MAX_FOLLOWS_PER_DAY = 10

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
MIN_MARKET_VOLUME_24H = 100.0    # contracts traded in the last 24h (tunable; live data shows tens-to-hundreds typical)

# ── Trend poller (Bluesky-trend-selected Kalshi markets; peer to the broad allowlist poll) ──
TREND_INTERVAL_SECONDS = 900     # `pulse run --source trend` cadence: 15 min
TREND_LIMIT = 25                 # Bluesky trends pulled per cycle
TREND_MAX_MARKETS = 60           # cap snapshots/cycle (top-N by volume) — bounds bloat even when a
                                 # huge trend like "World Cup" maps to hundreds of markets
TREND_MIN_VOLUME_24H = MIN_MARKET_VOLUME_24H  # volume floor for trend-matched markets
# NO category allowlist here — trend-relevance is the filter — but keep the project's agri/food
# exclusion. (Verify the exact Kalshi category name(s) against live data when tuning.)
TREND_EXCLUDE_CATEGORIES = ("Agriculture",)

# ── HTTP client resilience ──
HTTP_TIMEOUT_SECONDS = 10.0
HTTP_MAX_RETRIES = 3

# ── Dashboard (read-only over the DB; MAY also live-fetch small ephemeral data — see memory
#    `dashboard-external-fetch-ok`) ──
DASHBOARD_HOST = os.environ.get("PULSE_DASHBOARD_HOST", "127.0.0.1")
DASHBOARD_PORT = int(os.environ.get("PULSE_DASHBOARD_PORT", "8440"))
# Trending-topics widget: fetch live from Bluesky, cached server-side so viewers/refreshes don't
# hammer the (unspecced) endpoint. Ephemeral — not persisted, no history.
DASHBOARD_TRENDS_TTL_SECONDS = 300  # re-fetch trends at most once per 5 min
DASHBOARD_TRENDS_LIMIT = 10         # trends shown in the widget

# ── Writer / persona ──
PERSONAS_DIR = os.environ.get("PULSE_PERSONAS_DIR", "personas")
PERSONA = os.environ.get("PULSE_PERSONA", "example")  # which persona to write as
WRITER_MAX_TOKENS = 150          # a Bluesky post is short; cap cost + runaway
MAX_DRAFT_AGE_HOURS = 24         # don't publish drafts older than this (stale news)
BLUESKY_MAX_GRAPHEMES = 300      # Bluesky post length limit
DRAFTS_PER_RUN = MAX_POSTS_PER_DAY  # cap events sent to the writer per draft cycle

# Event selection weights (which detected events are most worth posting; tune from data).
RULE_WEIGHTS = {
    "milestone": 3.0,      # "it just crossed 50%" — most newsworthy
    "odds_swing": 2.0,
    "volume_spike": 1.5,
    "new_market": 1.0,
}
