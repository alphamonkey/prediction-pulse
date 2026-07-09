"""GeneratorSource — the no-external-input ContentSource: seed Events from nothing.

The generator never calls the LLM; it emits operator-authored topic seeds that the writer
phrases in the persona's voice. Dedup is bucket-stable: within a bucket re-polls emit
nothing new, across buckets the topics rotate deterministically.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from pulse.pipeline import SourceSpec
from pulse.store.db import Database
from pulse.venue.generator import GeneratorSource
from pulse.venue.registry import SourceContext, make_source

_T = datetime(2026, 7, 9, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    database.connect()
    yield database
    database.close()


def test_emits_seed_event_with_generated_shape(db):
    source = GeneratorSource(topics=["bean history"])
    events = source.fetch_events(db, _T)
    assert len(events) == 1
    ev = events[0]
    assert ev.rule == "generated"
    assert ev.venue == "generator"
    assert ev.market_id == "bean-history"
    assert ev.value_kind is None
    assert ev.from_value is None and ev.to_value is None and ev.direction is None
    assert ev.magnitude == 1.0
    assert ev.headline == "bean history"
    assert ev.context["source_kind"] == "generated"
    assert ev.dedup_key.startswith("generated:bean-history:")
    assert db.has_posted(ev.dedup_key)  # contract: recorded before returned


def test_default_seed_when_no_topics(db):
    events = GeneratorSource().fetch_events(db, _T)
    assert len(events) == 1
    assert events[0].headline  # a generic, non-empty seed


def test_repoll_within_bucket_emits_nothing(db):
    source = GeneratorSource(topics=["beans"], bucket="1d")
    assert len(source.fetch_events(db, _T)) == 1
    assert source.fetch_events(db, _T + timedelta(hours=3)) == []  # same day-bucket


def test_next_bucket_emits_again(db):
    source = GeneratorSource(topics=["beans"], bucket="4h")
    first = source.fetch_events(db, _T)
    second = source.fetch_events(db, _T + timedelta(hours=4))
    assert len(first) == len(second) == 1
    assert first[0].dedup_key != second[0].dedup_key


def test_topics_rotate_across_buckets(db):
    topics = ["a", "b", "c"]
    source = GeneratorSource(topics=topics, bucket="4h")
    seen = [source.fetch_events(db, _T + timedelta(hours=4 * i))[0].headline
            for i in range(3)]
    assert sorted(seen) == topics  # every topic gets its turn before repeating


def test_count_emits_distinct_topics_capped_at_topic_count(db):
    source = GeneratorSource(topics=["a", "b"], count=5)
    events = source.fetch_events(db, _T)
    assert [e.headline for e in events] == ["a", "b"]  # capped, no dup dedup_keys


def test_restart_is_idempotent_within_bucket(db):
    # A new instance (process restart) must derive the SAME keys for the same bucket.
    GeneratorSource(topics=["beans"], bucket="1d").fetch_events(db, _T)
    fresh = GeneratorSource(topics=["beans"], bucket="1d")
    assert fresh.fetch_events(db, _T + timedelta(minutes=1)) == []


def test_bad_bucket_rejected():
    with pytest.raises(ValueError, match="bucket"):
        GeneratorSource(bucket="fortnight")


def test_registry_builds_generator_without_kalshi(db):
    built = []

    def factory():
        built.append(1)
        return object()

    ctx = SourceContext(kalshi_factory=factory)
    spec = SourceSpec("generator", {"topics": ["beans"], "count": 1, "bucket": "4h"})
    source = make_source(spec, ctx)
    assert isinstance(source, GeneratorSource)
    assert built == []  # no external input -> no Kalshi client
    ctx.close()


def test_registry_rejects_unknown_generator_option():
    with pytest.raises(ValueError, match=r"generator.*llm"):
        make_source(SourceSpec("generator", {"llm": True}), SourceContext())
