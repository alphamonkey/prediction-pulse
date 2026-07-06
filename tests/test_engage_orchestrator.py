"""Chunk 5: engage_once / EngageJob — filter → cap → idempotency → act → record."""

from __future__ import annotations

import pytest

from pulse.engage.base import EngageResult, SignalKind, Target
from pulse.engager import EngageJob, EngagePolicy, EngageReport, engage_once
from pulse.persona import Persona
from pulse.scheduler.base import Job
from pulse.store.db import Database

PERSONA = Persona(name="gnome", voice="be a gnome", channels=[{"platform": "bluesky"}])


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def _t(uri, text="kalshi market move", *, did=None):
    return Target(uri=uri, cid="c", author_did=did or f"did{uri}",
                  author_handle="h.bsky.social", text=text, source="topical-search")


class FakeSource:
    name = "fake"

    def __init__(self, targets):
        self._targets = targets

    def find_targets(self, *, limit):
        return self._targets[:limit]


class FakeEngager:
    name = "bluesky"

    def __init__(self, *, supported=(SignalKind.LIKE, SignalKind.REPOST, SignalKind.FOLLOW),
                 performed=True):
        self.supported_actions = frozenset(supported)
        self._performed = performed
        self.calls = []

    def engage(self, target, action):
        self.calls.append((action, target.uri, target.author_did))
        return EngageResult(action=action, target_uri=target.uri,
                            target_did=target.author_did, performed=self._performed)


def _policy(actions=(SignalKind.LIKE,), caps=None, allow=("kalshi",), deny=("election",)):
    caps = caps or {a: 30 for a in actions}
    return EngagePolicy(allow=list(allow), deny=list(deny), actions=tuple(actions),
                        caps=caps, queries=list(allow))


def test_likes_relevant_targets_and_records(db):
    src = FakeSource([_t("at://1"), _t("at://2"), _t("at://3")])
    eng = FakeEngager()
    report = engage_once(db, src, eng, PERSONA, _policy(), limit=10)
    assert isinstance(report, EngageReport)
    assert report.performed == 3
    assert all(a == SignalKind.LIKE for a, _, _ in eng.calls)
    assert db.signals_today("bluesky", SignalKind.LIKE) == 3


def test_filters_out_irrelevant_and_denylisted(db):
    src = FakeSource([
        _t("at://1", "kalshi market is wild"),
        _t("at://2", "my lunch photo"),               # off-topic
        _t("at://3", "kalshi on the election today"),  # denylisted
    ])
    eng = FakeEngager()
    report = engage_once(db, src, eng, PERSONA, _policy(), limit=10)
    assert report.performed == 1
    assert eng.calls == [(SignalKind.LIKE, "at://1", "didat://1")]


def test_respects_per_action_cap(db):
    src = FakeSource([_t(f"at://{i}") for i in range(5)])
    report = engage_once(db, src, FakeEngager(), PERSONA,
                         _policy(caps={SignalKind.LIKE: 2}), limit=10)
    assert report.performed == 2
    assert db.signals_today("bluesky", SignalKind.LIKE) == 2


def test_idempotent_skips_already_liked(db):
    db.record_interaction("gnome", "bluesky", SignalKind.LIKE,
                          target_uri="at://1", target_did="didat://1")
    src = FakeSource([_t("at://1"), _t("at://2")])
    eng = FakeEngager()
    report = engage_once(db, src, eng, PERSONA, _policy(), limit=10)
    assert [c[1] for c in eng.calls] == ["at://2"]
    assert report.performed == 1


def test_dryrun_records_nothing(db):
    src = FakeSource([_t("at://1"), _t("at://2")])
    eng = FakeEngager(performed=False)
    report = engage_once(db, src, eng, PERSONA, _policy(), limit=10)
    assert report.would == 2
    assert report.performed == 0
    assert db.signals_today("bluesky", SignalKind.LIKE) == 0


def test_action_unsupported_by_engager_is_skipped(db):
    src = FakeSource([_t("at://1")])
    eng = FakeEngager(supported=(SignalKind.LIKE,))  # cannot follow
    report = engage_once(db, src, eng, PERSONA,
                         _policy(actions=(SignalKind.FOLLOW,), caps={SignalKind.FOLLOW: 10}), limit=10)
    assert eng.calls == []
    assert report.performed == 0


def test_follow_is_keyed_on_did_and_idempotent(db):
    src = FakeSource([_t("at://1", did="did:plc:z")])
    pol = _policy(actions=(SignalKind.FOLLOW,), caps={SignalKind.FOLLOW: 10})
    first = engage_once(db, src, FakeEngager(), PERSONA, pol, limit=10)
    second = engage_once(db, src, FakeEngager(), PERSONA, pol, limit=10)
    assert first.performed == 1
    assert second.performed == 0  # already following that did
    assert db.has_interacted("gnome", "bluesky", SignalKind.FOLLOW, target_did="did:plc:z")


def test_engage_once_never_targets_self(db):
    self_t = Target(uri="at://self", cid="c", author_did="did:self",
                    author_handle="gnome.bsky.social", text="kalshi market move", source="s")
    src = FakeSource([self_t, _t("at://other")])
    eng = FakeEngager()
    report = engage_once(db, src, eng, PERSONA, _policy(), limit=10,
                         self_handles=("gnome.bsky.social",))
    assert [c[1] for c in eng.calls] == ["at://other"]  # our own post is skipped
    assert report.performed == 1


def test_engage_job_never_targets_self(db, monkeypatch):
    persona = Persona(name="gnome", voice="v",
                      channels=[{"platform": "bluesky", "handle": "gnome.bsky.social"}])
    eng = FakeEngager()
    self_t = Target(uri="at://self", cid="c", author_did="did:self",
                    author_handle="gnome.bsky.social", text="kalshi market move", source="s")
    monkeypatch.setattr("pulse.engager.make_engager", lambda channel: eng)
    monkeypatch.setattr("pulse.engager.make_target_source",
                        lambda channel, policy: FakeSource([self_t, _t("at://other")]))
    report = EngageJob(db, persona, _policy(), limit=10).run()
    assert [c[1] for c in eng.calls] == ["at://other"]  # channel handle → self excluded end-to-end
    assert report.performed == 1


def test_engage_job_is_named_job_and_loops_channels(db, monkeypatch):
    eng = FakeEngager()
    monkeypatch.setattr("pulse.engager.make_engager", lambda channel: eng)
    monkeypatch.setattr("pulse.engager.make_target_source",
                        lambda channel, policy: FakeSource([_t("at://1")]))
    job = EngageJob(db, PERSONA, _policy(), limit=10)
    assert job.name == "engage"
    assert isinstance(job, Job)
    report = job.run()
    assert report.performed == 1
    assert eng.calls == [(SignalKind.LIKE, "at://1", "didat://1")]
