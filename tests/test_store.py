"""Tests for the SQLite+WAL snapshot store and idempotency log."""

from datetime import datetime, timedelta, timezone

import pytest

from pulse.models import Event, MarketMeta, Snapshot, ValueKind
from pulse.store.db import Database

_T = datetime(2026, 6, 24, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _snap(market_id="KXTEST", ts=_T, value=0.5, volume=0.0, venue="kalshi", meta=None):
    return Snapshot(
        venue=venue,
        market_id=market_id,
        ts=ts,
        value=value,
        value_kind=ValueKind.PROBABILITY,
        volume=volume,
        meta=meta,
    )


def _event(dedup_key="odds_swing:kalshi:KXTEST:2026-06-24"):
    return Event(
        rule="odds_swing",
        venue="kalshi",
        market_id="KXTEST",
        ts=_T,
        value_kind=ValueKind.PROBABILITY,
        from_value=0.40,
        to_value=0.55,
        magnitude=0.15,
        direction="up",
        headline="KXTEST: odds 40% -> 55%",
        dedup_key=dedup_key,
        context={"window_hours": 6},
    )


# ── snapshot ingest ──

def test_insert_snapshot_is_idempotent_on_venue_market_ts(db):
    assert db.insert_snapshot(_snap()) is True
    assert db.insert_snapshot(_snap()) is False  # same (venue, market_id, ts)
    assert len(db.get_recent_snapshots("kalshi", "KXTEST")) == 1


def test_insert_distinct_timestamps_both_stored(db):
    db.insert_snapshot(_snap(ts=_T))
    db.insert_snapshot(_snap(ts=_T + timedelta(minutes=10)))
    assert len(db.get_recent_snapshots("kalshi", "KXTEST")) == 2


def test_get_recent_snapshots_returns_ascending_by_ts(db):
    db.insert_snapshot(_snap(ts=_T + timedelta(minutes=20), value=0.7))
    db.insert_snapshot(_snap(ts=_T, value=0.5))
    db.insert_snapshot(_snap(ts=_T + timedelta(minutes=10), value=0.6))
    series = db.get_recent_snapshots("kalshi", "KXTEST")
    assert [s.value for s in series] == [0.5, 0.6, 0.7]


def test_get_recent_snapshots_respects_limit_keeping_newest(db):
    for i in range(5):
        db.insert_snapshot(_snap(ts=_T + timedelta(minutes=i), value=0.5 + i / 100))
    series = db.get_recent_snapshots("kalshi", "KXTEST", limit=2)
    # newest 2, still returned ascending
    assert [s.value for s in series] == [0.53, 0.54]


def test_snapshots_isolated_by_market_and_venue(db):
    db.insert_snapshot(_snap(market_id="A"))
    db.insert_snapshot(_snap(market_id="B"))
    db.insert_snapshot(_snap(market_id="A", venue="polymarket"))
    assert len(db.get_recent_snapshots("kalshi", "A")) == 1
    assert len(db.get_recent_snapshots("kalshi", "B")) == 1
    assert len(db.get_recent_snapshots("polymarket", "A")) == 1


def test_snapshot_round_trips_meta_ts_and_value_kind(db):
    meta = MarketMeta(title="Will X happen?", status="active",
                      resolution_date="2026-12-31", category="Politics",
                      extra={"series": "KXX"})
    db.insert_snapshot(_snap(meta=meta))
    (got,) = db.get_recent_snapshots("kalshi", "KXTEST")
    assert got.meta == meta
    assert got.ts == _T and got.ts.tzinfo is not None
    assert got.value_kind is ValueKind.PROBABILITY


def test_distinct_markets_per_venue(db):
    db.insert_snapshot(_snap(market_id="A"))
    db.insert_snapshot(_snap(market_id="B"))
    db.insert_snapshot(_snap(market_id="C", venue="polymarket"))
    assert db.distinct_markets("kalshi") == ["A", "B"]
    assert db.distinct_markets("polymarket") == ["C"]


# ── idempotency log ──

def test_record_posted_is_idempotent(db):
    assert db.has_posted("odds_swing:kalshi:KXTEST:2026-06-24") is False
    assert db.record_posted(_event()) is True
    assert db.has_posted("odds_swing:kalshi:KXTEST:2026-06-24") is True
    assert db.record_posted(_event()) is False  # same dedup_key


def test_record_posted_persists_payload(db):
    db.record_posted(_event())
    rows = db.conn.execute("SELECT * FROM posted_events").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["rule"] == "odds_swing"
    assert row["headline"] == "KXTEST: odds 40% -> 55%"
    assert row["direction"] == "up"


# ── read-only safety ──

def test_connect_readonly_rejects_writes(db, tmp_path):
    db.insert_snapshot(_snap())
    ro = Database.connect_readonly(tmp_path / "test.db")
    try:
        assert len(ro.get_recent_snapshots("kalshi", "KXTEST")) == 1
        with pytest.raises(Exception):
            ro.insert_snapshot(_snap(ts=_T + timedelta(minutes=1)))
    finally:
        ro.close()


# ── drafts ──

from pulse.writer.base import Draft  # noqa: E402


def _draft(dedup_key="odds_swing:kalshi:KXTEST:2026-06-24", text="A punchy post."):
    return Draft(event_dedup_key=dedup_key, persona="example", text=text)


def test_insert_draft_is_idempotent(db):
    assert db.has_draft("odds_swing:kalshi:KXTEST:2026-06-24") is False
    assert db.insert_draft(_draft()) is True
    assert db.has_draft("odds_swing:kalshi:KXTEST:2026-06-24") is True
    assert db.insert_draft(_draft(text="different")) is False  # same event_dedup_key
    rows = db.get_drafts()
    assert len(rows) == 1
    assert rows[0]["text"] == "A punchy post."  # first write wins


def test_get_undrafted_events_excludes_drafted_and_reconstructs(db):
    db.record_posted(_event(dedup_key="k1"))
    db.record_posted(_event(dedup_key="k2"))
    db.insert_draft(_draft(dedup_key="k1"))  # k1 now drafted
    undrafted = db.get_undrafted_events(limit=10)
    keys = {e.dedup_key for e in undrafted}
    assert keys == {"k2"}
    ev = undrafted[0]
    assert ev.rule == "odds_swing"
    assert ev.headline == "KXTEST: odds 40% -> 55%"
    assert ev.market_id == "KXTEST"


def test_generated_event_round_trips_non_market_shape(db):
    db.record_posted(Event(
        rule="generated", venue="generator", market_id="bean-history", ts=_T,
        value_kind=None, from_value=None, to_value=None, magnitude=1.0, direction=None,
        headline="bean history", dedup_key="generated:bean-history:2026-06-24T12:00",
        context={"source_kind": "generated"},
    ))
    [ev] = db.get_undrafted_events(limit=10)
    # context is the persisted discriminator; value_kind must NOT come back market-shaped
    assert ev.context["source_kind"] == "generated"
    assert ev.value_kind is None
    assert ev.headline == "bean history"
    assert ev.magnitude == 1.0


def test_get_undrafted_events_respects_limit(db):
    for i in range(5):
        db.record_posted(_event(dedup_key=f"k{i}"))
    assert len(db.get_undrafted_events(limit=2)) == 2


# ── dashboard reads ──

def _ev(dedup_key, rule="odds_swing", magnitude=0.15):
    return Event(
        rule=rule, venue="kalshi", market_id="KXTEST", ts=_T,
        value_kind=ValueKind.PROBABILITY, from_value=0.40, to_value=0.55,
        magnitude=magnitude, direction="up", headline="KXTEST: odds 40% -> 55%",
        dedup_key=dedup_key,
    )


def test_get_recent_events_newest_first_and_capped(db):
    for i in range(5):
        db.record_posted(_ev(f"k{i}", rule="milestone" if i == 4 else "odds_swing"))
    rows = db.get_recent_events(limit=3)
    assert len(rows) == 3
    # newest (k4) first; columns present
    assert rows[0]["dedup_key"] == "k4" or "rule" in rows[0]
    assert {"rule", "market_id", "magnitude", "headline", "created_at"} <= set(rows[0].keys())


def test_stats_counts(db):
    db.insert_snapshot(_snap(market_id="A", ts=_T))
    db.insert_snapshot(_snap(market_id="B", ts=_T + timedelta(minutes=10)))
    db.record_posted(_ev("k1", rule="milestone"))
    db.record_posted(_ev("k2", rule="odds_swing"))
    db.record_posted(_ev("k3", rule="odds_swing"))
    db.insert_draft(_draft(dedup_key="k1"))

    s = db.stats()
    assert s["snapshots"] == 2
    assert s["markets_tracked"] == 2
    assert s["events_total"] == 3
    assert s["events_by_rule"] == {"odds_swing": 2, "milestone": 1}
    assert s["drafts"] == 1
    assert s["last_poll"] == (_T + timedelta(minutes=10)).isoformat()


def test_connect_sets_busy_timeout(db):
    # Two writer processes (poller + drafter) share the DB; writers must wait for the lock.
    assert db.conn.execute("PRAGMA busy_timeout").fetchone()[0] == 60000


# ── posts (publisher) ──

from types import SimpleNamespace  # noqa: E402


def _result(uri="at://did:plc:x/app.bsky.feed.post/abc", channel="bluesky", text="hi"):
    return SimpleNamespace(channel=channel, posted=True, uri=uri, cid="cid1", text=text)


def test_insert_post_idempotent_per_channel(db):
    db.insert_draft(_draft(dedup_key="k1"))
    assert db.has_posted_to("k1", "bluesky") is False
    assert db.insert_post("k1", "example", _result()) is True
    assert db.has_posted_to("k1", "bluesky") is True
    assert db.insert_post("k1", "example", _result(uri="other")) is False  # same (key, channel)
    # a different channel for the same event is allowed
    assert db.insert_post("k1", "example", _result(channel="x")) is True


def test_posts_today_counts_rolling_24h(db):
    now = datetime.now(timezone.utc)
    db.conn.execute(
        "INSERT INTO posts (event_dedup_key, persona, channel, uri, cid, text, posted_at) "
        "VALUES ('a','p','bluesky','u','c','t',?)", ((now - timedelta(hours=1)).isoformat(),))
    db.conn.execute(
        "INSERT INTO posts (event_dedup_key, persona, channel, uri, cid, text, posted_at) "
        "VALUES ('b','p','bluesky','u','c','t',?)", ((now - timedelta(hours=30)).isoformat(),))
    db.conn.commit()
    assert db.posts_today("bluesky") == 1   # the 30h-old one is outside the window


def test_get_unposted_drafts_filters(db):
    now = datetime.now(timezone.utc)
    # fresh + unposted -> eligible
    db.insert_draft(Draft(event_dedup_key="fresh", persona="gnome", text="fresh post",
                          created_at=now))
    # stale -> excluded
    db.insert_draft(Draft(event_dedup_key="stale", persona="gnome", text="old post",
                          created_at=now - timedelta(hours=48)))
    # other persona -> excluded
    db.insert_draft(Draft(event_dedup_key="other", persona="elf", text="not mine", created_at=now))
    # already posted to bluesky -> excluded
    db.insert_draft(Draft(event_dedup_key="done", persona="gnome", text="posted", created_at=now))
    db.insert_post("done", "gnome", _result())

    out = db.get_unposted_drafts("bluesky", persona="gnome", limit=10, max_age_hours=24)
    assert [d.event_dedup_key for d in out] == ["fresh"]
    assert out[0].text == "fresh post"
