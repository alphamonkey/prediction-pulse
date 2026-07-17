"""The acceptance test for the whole multi-channel seam.

The claim being tested is a PLATFORM claim, not a Mastodon one: any persona, present or future, can
opt into a channel by editing `persona.toml` and adding a secret — and touching **zero Python**.

So these tests load the SAME persona twice, once Bluesky-only and once with a `[[channels]]`
mastodon block appended, and assert the pipeline fans out. The only difference between the two runs
is a TOML string. If a future change breaks that, it breaks here.
"""

from __future__ import annotations

import pytest

from pulse.engage.base import SignalKind  # noqa: F401  (imported for the policy path)
from pulse.metrics.base import AccountStats, MetricKind, PostEngagement
from pulse.models import _now
from pulse.persona import load_persona
from pulse.publish.base import PostResult
from pulse.store.db import Database
from pulse.supervisor import build_supervised
from pulse.venue.registry import SourceContext

_MASTODON_BLOCK = """
[[channels]]
platform = "mastodon"
instance = "https://mastodon.social"
handle = "@beans@mastodon.social"
"""

_TOML = """
display_name = "Bean Facts"

[[channels]]
platform = "bluesky"
handle = "beans.test"
{extra}
[pipeline.poll]
interval = 60

[[pipeline.poll.source]]
type = "generator"
topics = ["bean history"]
bucket = "4h"

[pipeline.draft]

[pipeline.publish]
windows = []

[pipeline.metrics]
"""


@pytest.fixture
def make_db(tmp_path):
    """One fresh connection to the persona's file per call — as the supervisor does."""
    path = str(tmp_path / "beans.db")
    made = []

    def factory() -> Database:
        db = Database(path)
        db.connect()
        made.append(db)
        return db

    yield factory
    for db in made:
        db.close()


def _persona(tmp_path, *, mastodon: bool):
    """The same persona, differing ONLY by the presence of a [[channels]] mastodon block."""
    pdir = tmp_path / "personas" / "beans"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "system_prompt.md").write_text("You invent silly bean facts.")
    (pdir / "persona.toml").write_text(
        _TOML.format(extra=_MASTODON_BLOCK if mastodon else ""))
    return load_persona("beans", root=tmp_path / "personas")


def _no_kalshi():
    raise AssertionError("a generator persona must never construct a Kalshi client")


def _run(persona, make_db, *, jobs=("poll:generator", "draft", "publish")):
    entries = build_supervised(persona, make_db,
                               source_context=SourceContext(kalshi_factory=_no_kalshi))
    by_name = {e.name: e.job for e in entries}
    return {name: by_name[name].run() for name in jobs}, by_name


# ── one canonical draft, fanned out to every channel ──

@pytest.mark.parametrize("mastodon, channels", [(False, 1), (True, 2)])
def test_one_draft_fans_out_to_every_channel(tmp_path, make_db, monkeypatch, mastodon, channels):
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    persona = _persona(tmp_path, mastodon=mastodon)
    assert len(persona.channels) == channels

    reports, _ = _run(persona, make_db)

    # ONE draft either way — the draft is per event, not per channel. Adding a channel must not
    # double the writer's (paid) work.
    db = make_db()
    assert db.conn.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 1
    # ... but it is offered to every channel.
    assert reports["publish"].would_post == channels


def test_the_draft_is_written_to_the_tightest_channels_limit(tmp_path, make_db, monkeypatch):
    """Bluesky's 300 still governs a Bluesky+Mastodon persona — otherwise the Bluesky publisher
    would truncate copy the writer thought it had room for."""
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    persona = _persona(tmp_path, mastodon=True)
    assert persona.draft_max_length() == 300

    _run(persona, make_db)
    text = make_db().conn.execute("SELECT text FROM drafts").fetchone()["text"]
    assert len(text) <= 300


# ── publishing: one event, one row per channel ──

class _FakePublisher:
    def __init__(self, platform, max_length):
        self.name = platform
        self.max_length = max_length

    def publish(self, draft, persona):
        return PostResult(channel=self.name, posted=True, uri=f"{self.name}://1",
                          cid="c", text=draft.text)


def test_publishing_records_one_post_per_channel_for_the_same_event(tmp_path, make_db, monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "dryrun")   # the fakes stand in for live publishers
    monkeypatch.setattr("pulse.publisher.make_publisher",
                        lambda channel: _FakePublisher(channel["platform"], 300))
    persona = _persona(tmp_path, mastodon=True)

    reports, _ = _run(persona, make_db)
    assert reports["publish"].posted == 2

    rows = make_db().conn.execute(
        "SELECT event_dedup_key, channel FROM posts ORDER BY channel").fetchall()
    # UNIQUE(event_dedup_key, channel) is what permits this: one event, two posts, deduped per
    # channel — so a re-run publishes neither twice.
    assert [r["channel"] for r in rows] == ["bluesky", "mastodon"]
    assert len({r["event_dedup_key"] for r in rows}) == 1


# ── metrics: each channel measured as its own account ──

class _FakeSource:
    def __init__(self, platform, followers):
        self.name = platform
        self._followers = followers
        self.supported_metrics = frozenset({MetricKind.LIKES})
        self.handles = []

    def account(self, handle):
        self.handles.append(handle)
        return AccountStats(followers=self._followers, follows=1, posts=1, fetched_at=_now())

    def engagement(self, uris):
        return [PostEngagement(u, self.name, _now(), {MetricKind.LIKES: 1}) for u in uris]


def test_metrics_snapshots_each_channel_separately(tmp_path, make_db, monkeypatch):
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    monkeypatch.setattr("pulse.publisher.make_publisher",
                        lambda channel: _FakePublisher(channel["platform"], 300))
    sources = {"bluesky": _FakeSource("bluesky", 9), "mastodon": _FakeSource("mastodon", 400)}
    monkeypatch.setattr("pulse.metrics.collect.make_engagement_source",
                        lambda channel: sources[channel["platform"]])
    persona = _persona(tmp_path, mastodon=True)

    reports, _ = _run(persona, make_db, jobs=("poll:generator", "draft", "publish", "metrics"))

    assert reports["metrics"].by_platform == {"bluesky": 9, "mastodon": 400}
    # Each source was asked about the account THAT channel declares — not the Bluesky one twice.
    assert sources["mastodon"].handles == ["@beans@mastodon.social"]
    assert sources["bluesky"].handles == ["beans.test"]

    db = make_db()
    rows = db.conn.execute(
        "SELECT platform, followers FROM account_snapshots ORDER BY platform").fetchall()
    assert [(r["platform"], r["followers"]) for r in rows] == [("bluesky", 9), ("mastodon", 400)]
    # The two accounts never blend into one series.
    assert db.follower_platforms() == ["bluesky", "mastodon"]
    assert [p["followers"] for p in db.follower_series(platform="mastodon")] == [400]


# ── the negative case: no Python knows this persona gained a channel ──

def test_adding_the_channel_needed_no_code_path_of_its_own(tmp_path, make_db, monkeypatch):
    """Belt and braces: the two personas differ only by a TOML string, and both build the same job
    set. Nothing about `mastodon` is special-cased in the supervisor."""
    monkeypatch.setenv("PULSE_MODE", "dryrun")
    one = build_supervised(_persona(tmp_path, mastodon=False), make_db,
                           source_context=SourceContext(kalshi_factory=_no_kalshi))
    two = build_supervised(_persona(tmp_path, mastodon=True), make_db,
                           source_context=SourceContext(kalshi_factory=_no_kalshi))
    assert {e.name for e in one} == {e.name for e in two}
