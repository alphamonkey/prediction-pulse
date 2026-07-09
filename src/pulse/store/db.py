"""SQLite + WAL persistence for normalized snapshots and the posted-events log.

Concurrency: WAL mode lets the (future) dashboard read while the worker writes; all
writes are serialized by a `threading.Lock` and committed immediately. Idempotency is
enforced with `INSERT OR IGNORE` on natural keys — re-ingesting a snapshot or re-recording
an event is a no-op. Mirrors the discipline in kalshi-edge's `edge/core/db.py`.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path

from pulse.config import MAX_RECENT_SNAPSHOTS
from pulse.engage.base import SignalKind
from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.models import Event, MarketMeta, Snapshot, ValueKind, _now
from pulse.writer.base import Draft

_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    venue       TEXT NOT NULL,
    market_id   TEXT NOT NULL,
    ts          TEXT NOT NULL,
    value       REAL NOT NULL,
    value_kind  TEXT NOT NULL,
    volume      REAL NOT NULL DEFAULT 0,
    meta        TEXT,
    UNIQUE(venue, market_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_snap_market_ts
    ON market_snapshots(venue, market_id, ts DESC);

CREATE TABLE IF NOT EXISTS posted_events (
    dedup_key   TEXT PRIMARY KEY,
    rule        TEXT NOT NULL,
    venue       TEXT NOT NULL,
    market_id   TEXT NOT NULL,
    ts          TEXT NOT NULL,
    from_value  REAL,
    to_value    REAL,
    magnitude   REAL,
    direction   TEXT,
    headline    TEXT NOT NULL,
    context     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_posted_market ON posted_events(venue, market_id);

CREATE TABLE IF NOT EXISTS drafts (
    event_dedup_key  TEXT PRIMARY KEY,
    persona          TEXT NOT NULL,
    text             TEXT NOT NULL,
    media            TEXT,
    status           TEXT NOT NULL DEFAULT 'draft',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS posts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    event_dedup_key  TEXT NOT NULL,
    persona          TEXT NOT NULL,
    channel          TEXT NOT NULL,
    uri              TEXT,
    cid              TEXT,
    text             TEXT NOT NULL,
    posted_at        TEXT NOT NULL,
    UNIQUE(event_dedup_key, channel)
);

-- Account-level counts over time (one row per metrics poll) — drives the follower-growth chart.
CREATE TABLE IF NOT EXISTS account_snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          TEXT NOT NULL,
    followers   INTEGER NOT NULL,
    follows     INTEGER NOT NULL,
    posts       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_account_ts ON account_snapshots(ts);

-- Per-post engagement, stored TALL (one row per uri+metric) so platforms with different metric
-- sets need no schema change. Latest-only: re-collecting upserts in place (no time-series).
CREATE TABLE IF NOT EXISTS post_metrics (
    uri         TEXT NOT NULL,
    platform    TEXT NOT NULL,
    metric      TEXT NOT NULL,
    value       INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    PRIMARY KEY (uri, metric)
);

-- Outbound engagement actions we've taken (like/repost/follow). One row per action+target;
-- UNIQUE keeps us from ever engaging the same target twice. target_did keys follows; target_uri
-- keys post-level signals (the unused one is '').
CREATE TABLE IF NOT EXISTS interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    persona     TEXT NOT NULL,
    channel     TEXT NOT NULL,
    action      TEXT NOT NULL,
    target_uri  TEXT NOT NULL DEFAULT '',
    target_did  TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL,
    UNIQUE(persona, channel, action, target_uri, target_did)
);
CREATE INDEX IF NOT EXISTS idx_interactions_cap ON interactions(channel, action, created_at);
"""

# Passive metrics are views, not interactions — excluded from "total engagements" and the leaderboard,
# and used as the denominator for a true engagement rate when a platform provides them.
PASSIVE_METRICS = frozenset({MetricKind.IMPRESSIONS, MetricKind.VIDEO_VIEWS})


# How long a writer waits for the lock before erroring (poller + drafter share the DB).
BUSY_TIMEOUT_MS = 60000  # 60s — two writers (poller + drafter) share the DB; ride out contention


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self.conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # Born reclaimable: incremental auto_vacuum lets `reclaim()` hand freed pages back to the OS
        # after a prune. MUST precede the first CREATE TABLE to take effect on a fresh DB; on an
        # already-created DB it's inert until a full VACUUM converts it (see `vacuum()`).
        self.conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
        self.conn.execute("PRAGMA journal_mode=WAL")
        # Two writer processes (poller + drafter) share this DB; WAL serializes writers, so make
        # a writer wait for the lock rather than erroring. Explicit so it doesn't depend on
        # sqlite3.connect's implicit timeout default.
        self.conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self._migrate()
        self.conn.commit()

    def _migrate(self) -> None:
        """Additive migrations for DBs created before a column existed."""
        # No migrations yet; placeholder mirroring kalshi-edge's pattern.

    @classmethod
    def connect_readonly(cls, path: str | Path) -> Database:
        """Open a read-only connection (for the future dashboard)."""
        db = cls(path)
        db.conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        db.conn.row_factory = sqlite3.Row
        db.conn.execute("PRAGMA query_only=ON")
        return db

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # ── snapshots ──

    def insert_snapshot(self, snap: Snapshot) -> bool:
        """Record a snapshot. Returns True if newly inserted, False if a duplicate."""
        assert self.conn is not None
        meta_json = json.dumps(asdict(snap.meta)) if snap.meta is not None else None
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO market_snapshots
                   (venue, market_id, ts, value, value_kind, volume, meta)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    snap.venue, snap.market_id, snap.ts.isoformat(), snap.value,
                    snap.value_kind.value, snap.volume, meta_json,
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def insert_snapshots(self, snaps) -> int:
        """Bulk-insert convenience (seeding/tests). Returns count newly inserted."""
        return sum(int(self.insert_snapshot(s)) for s in snaps)

    def get_recent_snapshots(
        self, venue: str, market_id: str, limit: int = MAX_RECENT_SNAPSHOTS
    ) -> list[Snapshot]:
        """The most recent `limit` snapshots for a market, returned ASCENDING by ts."""
        assert self.conn is not None
        rows = self.conn.execute(
            """SELECT * FROM market_snapshots
               WHERE venue = ? AND market_id = ?
               ORDER BY ts DESC LIMIT ?""",
            (venue, market_id, limit),
        ).fetchall()
        return [self._row_to_snapshot(r) for r in reversed(rows)]

    def distinct_markets(self, venue: str) -> list[str]:
        assert self.conn is not None
        rows = self.conn.execute(
            "SELECT DISTINCT market_id FROM market_snapshots WHERE venue = ? ORDER BY market_id",
            (venue,),
        ).fetchall()
        return [r["market_id"] for r in rows]

    # ── retention (market_snapshots grows unbounded without this) ──

    def prune_snapshots(self, before: datetime) -> int:
        """Delete snapshots strictly older than `before`; return the number of rows deleted.

        `ts` is stored as tz-aware ISO-8601 UTC, so the text comparison is chronological. Detector
        reads only the last few hours per market, so a horizon of days is always safe.
        """
        assert self.conn is not None
        with self._lock:
            cur = self.conn.execute(
                "DELETE FROM market_snapshots WHERE ts < ?", (before.isoformat(),)
            )
            self.conn.commit()
            return cur.rowcount

    def reclaim(self) -> None:
        """Hand freed pages back to the OS and truncate the WAL — the cheap follow-up to a prune.

        A DELETE frees pages but SQLite keeps them in the file until a vacuum; with incremental
        auto_vacuum this is a bounded, WAL-friendly operation (no whole-file rewrite, no exclusive
        lock). The wal_checkpoint(TRUNCATE) keeps the WAL from retaining the reclaimed space.
        """
        assert self.conn is not None
        with self._lock:
            self.conn.execute("PRAGMA incremental_vacuum")
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()

    def vacuum(self) -> None:
        """One-time compaction + conversion to incremental auto_vacuum for an existing DB.

        Setting auto_vacuum in `connect()` is inert on a DB whose tables already exist; a full VACUUM
        is what actually converts it (and reclaims all currently-free space at once). VACUUM needs an
        EXCLUSIVE lock, so run this with the other writer services stopped.
        """
        assert self.conn is not None
        with self._lock:
            self.conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            self.conn.execute("VACUUM")
            self.conn.commit()

    @staticmethod
    def _row_to_snapshot(row: sqlite3.Row) -> Snapshot:
        meta = None
        if row["meta"] is not None:
            meta = MarketMeta(**json.loads(row["meta"]))
        return Snapshot(
            venue=row["venue"],
            market_id=row["market_id"],
            ts=datetime.fromisoformat(row["ts"]),
            value=row["value"],
            value_kind=ValueKind(row["value_kind"]),
            volume=row["volume"],
            meta=meta,
        )

    # ── idempotency log ──

    def has_posted(self, dedup_key: str) -> bool:
        assert self.conn is not None
        row = self.conn.execute(
            "SELECT 1 FROM posted_events WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        return row is not None

    def record_posted(self, event: Event) -> bool:
        """Record an emitted event. Returns True if newly recorded, False if a duplicate.

        Race-safe backstop: the INSERT OR IGNORE means two concurrent callers cannot both
        observe a True for the same dedup_key.
        """
        assert self.conn is not None
        from pulse.models import _now

        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO posted_events
                   (dedup_key, rule, venue, market_id, ts, from_value, to_value,
                    magnitude, direction, headline, context, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.dedup_key, event.rule, event.venue, event.market_id,
                    event.ts.isoformat(), event.from_value, event.to_value,
                    event.magnitude, event.direction, event.headline,
                    json.dumps(event.context), _now().isoformat(),
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    # ── drafts ──

    def insert_draft(self, draft) -> bool:
        """Record a post draft. Returns True if newly inserted, False if already drafted."""
        assert self.conn is not None
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO drafts
                   (event_dedup_key, persona, text, media, status, created_at)
                   VALUES (?, ?, ?, ?, 'draft', ?)""",
                (
                    draft.event_dedup_key, draft.persona, draft.text,
                    json.dumps(draft.media), draft.created_at.isoformat(),
                ),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def has_draft(self, dedup_key: str) -> bool:
        assert self.conn is not None
        row = self.conn.execute(
            "SELECT 1 FROM drafts WHERE event_dedup_key = ?", (dedup_key,)
        ).fetchone()
        return row is not None

    def get_drafts(self, limit: int = 100) -> list[dict]:
        assert self.conn is not None
        rows = self.conn.execute(
            "SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── dashboard reads (read-only-safe) ──

    def get_recent_events(self, limit: int = 20) -> list[dict]:
        """The most recent detected events (from posted_events), newest first."""
        assert self.conn is not None
        rows = self.conn.execute(
            """SELECT dedup_key, rule, venue, market_id, magnitude, direction,
                      headline, created_at
               FROM posted_events ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def stats(self) -> dict:
        """High-level pipeline counts for the dashboard."""
        assert self.conn is not None
        q = self.conn.execute
        by_rule = {
            r["rule"]: r["n"]
            for r in q("SELECT rule, COUNT(*) n FROM posted_events GROUP BY rule ORDER BY n DESC")
        }
        return {
            "snapshots": q("SELECT COUNT(*) FROM market_snapshots").fetchone()[0],
            "markets_tracked": q("SELECT COUNT(DISTINCT market_id) FROM market_snapshots").fetchone()[0],
            "events_total": q("SELECT COUNT(*) FROM posted_events").fetchone()[0],
            "events_by_rule": by_rule,
            "drafts": q("SELECT COUNT(*) FROM drafts").fetchone()[0],
            "last_poll": q("SELECT MAX(ts) FROM market_snapshots").fetchone()[0],
        }

    # ── posts (publisher) ──

    def insert_post(self, event_dedup_key: str, persona: str, result) -> bool:
        """Record a successful post. Returns True if newly recorded, False if a duplicate.

        Idempotency backstop: UNIQUE(event_dedup_key, channel) means a draft is never posted
        to the same channel twice, even under a race.
        """
        assert self.conn is not None
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO posts
                   (event_dedup_key, persona, channel, uri, cid, text, posted_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (event_dedup_key, persona, result.channel, result.uri, result.cid, result.text,
                 _now().isoformat()),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def has_posted_to(self, event_dedup_key: str, channel: str) -> bool:
        assert self.conn is not None
        row = self.conn.execute(
            "SELECT 1 FROM posts WHERE event_dedup_key = ? AND channel = ?",
            (event_dedup_key, channel),
        ).fetchone()
        return row is not None

    def posts_today(self, channel: str) -> int:
        """Posts to `channel` in the last 24h (rolling) — for the daily rate cap."""
        assert self.conn is not None
        cutoff = (_now() - timedelta(hours=24)).isoformat()
        return self.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE channel = ? AND posted_at >= ?",
            (channel, cutoff),
        ).fetchone()[0]

    # ── Engagement (interactions) ──────────────────────────────────────────────
    def record_interaction(
        self, persona: str, channel: str, action: SignalKind, *,
        target_uri: str = "", target_did: str = "",
    ) -> bool:
        """Record an engagement action. Returns True if newly recorded, False if a duplicate.

        UNIQUE(persona, channel, action, target_uri, target_did) means we never like/repost/follow
        the same target twice, even under a race.
        """
        assert self.conn is not None
        with self._lock:
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO interactions
                   (persona, channel, action, target_uri, target_did, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (persona, channel, action.value, target_uri, target_did, _now().isoformat()),
            )
            self.conn.commit()
            return cur.rowcount > 0

    def has_interacted(
        self, persona: str, channel: str, action: SignalKind, *,
        target_uri: str = "", target_did: str = "",
    ) -> bool:
        """Whether this action was already taken — matched on whichever key(s) you supply
        (uri for likes/reposts, did for follows)."""
        assert self.conn is not None
        clauses = ["persona = ?", "channel = ?", "action = ?"]
        params: list = [persona, channel, action.value]
        if target_uri:
            clauses.append("target_uri = ?")
            params.append(target_uri)
        if target_did:
            clauses.append("target_did = ?")
            params.append(target_did)
        row = self.conn.execute(
            f"SELECT 1 FROM interactions WHERE {' AND '.join(clauses)}", params
        ).fetchone()
        return row is not None

    def signals_today(self, channel: str, action: SignalKind) -> int:
        """Count of `action` on `channel` in the last 24h (rolling) — for the per-action cap."""
        assert self.conn is not None
        cutoff = (_now() - timedelta(hours=24)).isoformat()
        return self.conn.execute(
            "SELECT COUNT(*) FROM interactions WHERE channel = ? AND action = ? AND created_at >= ?",
            (channel, action.value, cutoff),
        ).fetchone()[0]

    def get_unposted_drafts(
        self, channel: str, *, persona: str, limit: int, max_age_hours: int
    ) -> list[Draft]:
        """A persona's drafts not yet posted to `channel`, fresher than the cutoff, newest first."""
        assert self.conn is not None
        cutoff = (_now() - timedelta(hours=max_age_hours)).isoformat()
        rows = self.conn.execute(
            """SELECT d.* FROM drafts d
               LEFT JOIN posts p ON p.event_dedup_key = d.event_dedup_key AND p.channel = ?
               WHERE p.id IS NULL AND d.persona = ? AND d.created_at >= ?
               ORDER BY d.created_at DESC LIMIT ?""",
            (channel, persona, cutoff, limit),
        ).fetchall()
        return [self._row_to_draft(r) for r in rows]

    @staticmethod
    def _row_to_draft(row: sqlite3.Row) -> Draft:
        return Draft(
            event_dedup_key=row["event_dedup_key"],
            persona=row["persona"],
            text=row["text"],
            media=json.loads(row["media"]) if row["media"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def get_undrafted_events(self, limit: int = 200) -> list[Event]:
        """Detected events (from posted_events) without a draft yet, newest first.

        Reconstructs the Event from the stored columns; `meta` isn't persisted there, so it's
        None (selection/writing rely on the stored `headline` + numeric fields).
        """
        assert self.conn is not None
        rows = self.conn.execute(
            """SELECT p.* FROM posted_events p
               LEFT JOIN drafts d ON d.event_dedup_key = p.dedup_key
               WHERE d.event_dedup_key IS NULL
               ORDER BY p.created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [self._row_to_event(r) for r in rows]

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> Event:
        context = json.loads(row["context"]) if row["context"] else {}
        # value_kind isn't a column; context is the persisted non-market discriminator.
        market_shaped = context.get("source_kind") != "generated"
        return Event(
            rule=row["rule"],
            venue=row["venue"],
            market_id=row["market_id"],
            ts=datetime.fromisoformat(row["ts"]),
            value_kind=ValueKind.PROBABILITY if market_shaped else None,
            from_value=row["from_value"],
            to_value=row["to_value"],
            magnitude=row["magnitude"],
            direction=row["direction"],
            headline=row["headline"],
            dedup_key=row["dedup_key"],
            context=context,
        )

    # ── engagement metrics (collector writes; dashboard reads) ──

    def insert_account_snapshot(self, stats: AccountStats) -> None:
        """Append one account-level snapshot (followers/follows/posts) for the growth series."""
        assert self.conn is not None
        with self._lock:
            self.conn.execute(
                "INSERT INTO account_snapshots (ts, followers, follows, posts) VALUES (?, ?, ?, ?)",
                (stats.fetched_at.isoformat(), stats.followers, stats.follows, stats.posts),
            )
            self.conn.commit()

    def upsert_post_metrics(self, items: list[PostEngagement]) -> int:
        """Upsert latest per-post metric counts (tall). Returns rows touched. Latest value wins."""
        assert self.conn is not None
        n = 0
        with self._lock:
            for e in items:
                for metric, value in e.metrics.items():
                    self.conn.execute(
                        """INSERT INTO post_metrics (uri, platform, metric, value, fetched_at)
                           VALUES (?, ?, ?, ?, ?)
                           ON CONFLICT(uri, metric) DO UPDATE SET
                             value=excluded.value,
                             fetched_at=excluded.fetched_at,
                             platform=excluded.platform""",
                        (e.uri, e.platform, MetricKind(metric).value, int(value),
                         e.fetched_at.isoformat()),
                    )
                    n += 1
            self.conn.commit()
        return n

    def recent_post_uris(self, platform: str, limit: int = 50) -> list[str]:
        """URIs of our recent posts to `platform` (newest first) — what to refresh engagement for."""
        assert self.conn is not None
        rows = self.conn.execute(
            """SELECT uri FROM posts
               WHERE channel = ? AND uri IS NOT NULL
               ORDER BY posted_at DESC, id DESC LIMIT ?""",
            (platform, limit),
        ).fetchall()
        return [r["uri"] for r in rows]

    def follower_series(self, days: int = 30, *, now: datetime | None = None) -> list[dict]:
        """Account follower count over the last `days`, ascending by ts — for the growth chart.

        `now` is injectable so tests can pin the window deterministically (defaults to wall clock).
        """
        assert self.conn is not None
        cutoff = ((now or _now()) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT ts, followers FROM account_snapshots WHERE ts >= ? ORDER BY ts ASC",
            (cutoff,),
        ).fetchall()
        return [{"ts": r["ts"], "followers": r["followers"]} for r in rows]

    def kpms(self, *, now: datetime | None = None) -> dict:
        """The content scorecard: follower growth + per-post engagement rates over the tall metrics.

        Returns only metrics actually present, so a richer platform (e.g. one with impressions)
        surfaces a true engagement rate while Bluesky shows per-post proxies. Empty-DB safe.
        `now` is injectable so tests can pin the 7-day window deterministically (defaults to wall clock).
        """
        assert self.conn is not None
        q = self.conn.execute

        latest = q("SELECT followers FROM account_snapshots ORDER BY ts DESC LIMIT 1").fetchone()
        followers = latest["followers"] if latest else None
        delta = None
        if followers is not None:
            cutoff = ((now or _now()) - timedelta(days=7)).isoformat()
            base = q("SELECT followers FROM account_snapshots WHERE ts >= ? ORDER BY ts ASC LIMIT 1",
                     (cutoff,)).fetchone()
            if base is not None:
                delta = followers - base["followers"]

        totals = {r["metric"]: r["total"] for r in
                  q("SELECT metric, SUM(value) total FROM post_metrics GROUP BY metric")}
        posts_measured = q("SELECT COUNT(DISTINCT uri) FROM post_metrics").fetchone()[0]

        def avg(metric: MetricKind) -> float:
            return round(totals.get(metric.value, 0) / posts_measured, 2) if posts_measured else 0.0

        total_engagements = sum(
            v for m, v in totals.items() if MetricKind(m) not in PASSIVE_METRICS
        )
        out = {
            "followers": followers,
            "follower_delta_7d": delta,
            "posts_measured": posts_measured,
            "totals": totals,
            "applause": avg(MetricKind.LIKES),
            "conversation": avg(MetricKind.REPLIES),
            "amplification": round(avg(MetricKind.REPOSTS) + avg(MetricKind.QUOTES), 2),
            "total_engagements": total_engagements,
        }
        impressions = totals.get(MetricKind.IMPRESSIONS.value, 0)
        if impressions:
            out["engagement_rate"] = round(total_engagements / impressions * 100, 2)
        return out

    def top_posts(self, limit: int = 5) -> list[dict]:
        """Our posts ranked by total interaction engagement (passive views excluded) — the leaderboard."""
        assert self.conn is not None
        rows = self.conn.execute(
            """SELECT pm.uri AS uri, COALESCE(p.text, '') AS text, pm.metric AS metric,
                      pm.value AS value
               FROM post_metrics pm
               LEFT JOIN posts p ON p.uri = pm.uri
               WHERE pm.metric NOT IN (?, ?)""",
            (MetricKind.IMPRESSIONS.value, MetricKind.VIDEO_VIEWS.value),
        ).fetchall()
        agg: dict[str, dict] = {}
        for r in rows:
            e = agg.setdefault(
                r["uri"], {"uri": r["uri"], "text": r["text"], "total": 0, "metrics": {}}
            )
            e["metrics"][r["metric"]] = r["value"]
            e["total"] += r["value"]
        return sorted(agg.values(), key=lambda e: e["total"], reverse=True)[:limit]
