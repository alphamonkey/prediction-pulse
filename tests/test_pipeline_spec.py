"""[pipeline.*] in persona.toml — the persona declares its own stack.

A job runs iff its section is present; omitted fields fall back to config defaults, making
config.py the defaults layer and persona.toml the policy layer.
"""

from __future__ import annotations

import pytest

from pulse import config
from pulse.persona import load_persona
from pulse.pipeline import PipelineSpec, SourceSpec, parse_pipeline


def test_no_pipeline_table_means_no_jobs():
    spec = parse_pipeline({})
    assert spec == PipelineSpec()
    assert spec.poll is None
    assert spec.draft is None
    assert spec.publish is None
    assert spec.engage is None
    assert spec.metrics is None


def test_poll_parses_sources_and_interval():
    spec = parse_pipeline({"poll": {"sources": ["trend"], "interval": 900}})
    assert spec.poll.sources == (SourceSpec("trend"),)
    assert spec.poll.interval == 900
    assert spec.poll.jitter == 0


def test_poll_defaults():
    spec = parse_pipeline({"poll": {}})
    assert spec.poll.sources == (SourceSpec("kalshi"),)
    assert spec.poll.interval == config.DEFAULT_INTERVAL_SECONDS


def test_poll_source_tables_parse_type_and_options():
    # [[pipeline.poll.source]] — a configured source; non-`type` keys pass through as options.
    spec = parse_pipeline({"poll": {"source": [
        {"type": "generator", "topics": ["bean history"], "count": 2},
        {"type": "trend"},
    ]}})
    assert spec.poll.sources == (
        SourceSpec("generator", {"topics": ["bean history"], "count": 2}),
        SourceSpec("trend"),
    )


def test_poll_source_table_requires_type():
    with pytest.raises(ValueError, match=r"poll.*source.*type"):
        parse_pipeline({"poll": {"source": [{"topics": ["beans"]}]}})


def test_poll_both_source_forms_rejected():
    with pytest.raises(ValueError, match=r"sources.*source|source.*sources"):
        parse_pipeline({"poll": {"sources": ["trend"], "source": [{"type": "generator"}]}})


def test_draft_defaults():
    spec = parse_pipeline({"draft": {}})
    assert spec.draft.interval == config.DRAFT_INTERVAL_SECONDS
    assert spec.draft.limit == config.DRAFTS_PER_RUN


def test_publish_parses_windows_and_defaults():
    spec = parse_pipeline({
        "publish": {
            "interval": 14400,
            "jitter": 600,
            "windows": [["07:00", "10:00"], ["17:00", "22:00"]],
            "tz": "Europe/London",
        }
    })
    assert spec.publish.interval == 14400
    assert spec.publish.jitter == 600
    assert spec.publish.windows == (("07:00", "10:00"), ("17:00", "22:00"))
    assert spec.publish.tz == "Europe/London"
    assert spec.publish.limit == config.MAX_POSTS_PER_DAY


def test_publish_defaults():
    spec = parse_pipeline({"publish": {}})
    assert spec.publish.interval == config.PUBLISH_INTERVAL_SECONDS
    assert spec.publish.windows == config.PUBLISH_WINDOWS
    assert spec.publish.tz == config.ACTIVE_TZ


def test_engage_windows_publish_alias_uses_personas_publish_windows():
    spec = parse_pipeline({
        "publish": {"windows": [["06:00", "09:00"]]},
        "engage": {"windows": "publish"},
    })
    assert spec.engage.windows == (("06:00", "09:00"),)


def test_engage_windows_publish_alias_without_publish_section():
    spec = parse_pipeline({"engage": {"windows": "publish"}})
    assert spec.engage.windows == config.PUBLISH_WINDOWS


def test_engage_defaults_and_allow_follows_queries():
    spec = parse_pipeline({"engage": {"queries": ["frogs", "ponds"]}})
    assert spec.engage.queries == ("frogs", "ponds")
    # allow defaults to the persona's OWN queries, not the global allowlist
    assert spec.engage.allow == ("frogs", "ponds")
    assert spec.engage.deny == config.ENGAGE_DENY
    assert spec.engage.actions == config.ENGAGE_ACTIONS
    assert spec.engage.interval == config.ENGAGE_INTERVAL_SECONDS
    assert spec.engage.windows == config.ENGAGE_WINDOWS
    assert spec.engage.limit == config.ENGAGE_TARGETS_PER_RUN
    assert spec.engage.caps == {
        "like": config.MAX_LIKES_PER_DAY,
        "repost": config.MAX_REPOSTS_PER_DAY,
        "follow": config.MAX_FOLLOWS_PER_DAY,
    }


def test_engage_explicit_allow_and_caps():
    spec = parse_pipeline({
        "engage": {
            "queries": ["frogs"],
            "allow": ["frogs", "toads"],
            "caps": {"like": 5, "repost": 1},
        }
    })
    assert spec.engage.allow == ("frogs", "toads")
    assert spec.engage.caps["like"] == 5
    assert spec.engage.caps["repost"] == 1
    # unspecified caps keep global defaults
    assert spec.engage.caps["follow"] == config.MAX_FOLLOWS_PER_DAY


def test_metrics_defaults():
    spec = parse_pipeline({"metrics": {}})
    assert spec.metrics.interval == config.METRICS_INTERVAL_SECONDS
    assert spec.metrics.post_limit == config.METRICS_POST_WINDOW


def test_unknown_section_rejected():
    with pytest.raises(ValueError, match="reply"):
        parse_pipeline({"reply": {}})


def test_unknown_key_rejected_with_section_name():
    with pytest.raises(ValueError, match=r"poll.*intervall"):
        parse_pipeline({"poll": {"intervall": 900}})


def test_malformed_window_pair_rejected():
    with pytest.raises(ValueError, match="windows"):
        parse_pipeline({"publish": {"windows": [["07:00"]]}})


def _write_persona(root, name: str, toml_body: str) -> None:
    pdir = root / name
    pdir.mkdir(parents=True)
    (pdir / "system_prompt.md").write_text("You are a test voice.")
    (pdir / "persona.toml").write_text(toml_body)


def test_load_persona_populates_pipeline(tmp_path):
    _write_persona(tmp_path, "frog", """
display_name = "Frog"

[[channels]]
platform = "bluesky"
handle = "frog.bsky.social"

[pipeline.poll]
sources = ["trend"]
interval = 600

[pipeline.metrics]
""")
    persona = load_persona("frog", root=tmp_path)
    assert persona.pipeline.poll.sources == (SourceSpec("trend"),)
    assert persona.pipeline.poll.interval == 600
    assert persona.pipeline.metrics is not None
    assert persona.pipeline.draft is None


def test_load_persona_without_pipeline_still_works(tmp_path):
    _write_persona(tmp_path, "plain", 'display_name = "Plain"\n')
    persona = load_persona("plain", root=tmp_path)
    assert persona.pipeline == PipelineSpec()
