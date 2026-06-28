"""Chunk 2: the interactions table — idempotency + per-action rolling caps."""

from __future__ import annotations

import pytest

from pulse.engage.base import SignalKind
from pulse.store.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def test_record_like_is_idempotent(db):
    first = db.record_interaction("gnome", "bluesky", SignalKind.LIKE,
                                  target_uri="at://x/1", target_did="did:plc:a")
    second = db.record_interaction("gnome", "bluesky", SignalKind.LIKE,
                                   target_uri="at://x/1", target_did="did:plc:a")
    assert first is True
    assert second is False


def test_has_interacted_tracks_likes_by_uri(db):
    assert not db.has_interacted("gnome", "bluesky", SignalKind.LIKE, target_uri="at://x/1")
    db.record_interaction("gnome", "bluesky", SignalKind.LIKE,
                          target_uri="at://x/1", target_did="did:plc:a")
    assert db.has_interacted("gnome", "bluesky", SignalKind.LIKE, target_uri="at://x/1")
    assert not db.has_interacted("gnome", "bluesky", SignalKind.LIKE, target_uri="at://x/2")


def test_follow_is_keyed_on_did_not_uri(db):
    first = db.record_interaction("gnome", "bluesky", SignalKind.FOLLOW,
                                  target_uri="", target_did="did:plc:a")
    again = db.record_interaction("gnome", "bluesky", SignalKind.FOLLOW,
                                  target_uri="", target_did="did:plc:a")
    assert first is True
    assert again is False
    assert db.has_interacted("gnome", "bluesky", SignalKind.FOLLOW, target_did="did:plc:a")
    assert not db.has_interacted("gnome", "bluesky", SignalKind.FOLLOW, target_did="did:plc:b")


def test_signals_today_counts_per_action(db):
    db.record_interaction("gnome", "bluesky", SignalKind.LIKE, target_uri="at://x/1", target_did="d")
    db.record_interaction("gnome", "bluesky", SignalKind.LIKE, target_uri="at://x/2", target_did="d")
    db.record_interaction("gnome", "bluesky", SignalKind.REPOST, target_uri="at://x/3", target_did="d")
    assert db.signals_today("bluesky", SignalKind.LIKE) == 2
    assert db.signals_today("bluesky", SignalKind.REPOST) == 1
    assert db.signals_today("bluesky", SignalKind.FOLLOW) == 0
