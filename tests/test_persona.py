"""Tests for persona loading — the user-authored voice + identity."""

import pytest

from pulse.persona import Persona, load_persona


def _write_persona(root, name, *, voice="You are a witty markets bot.", toml=None):
    pdir = root / name
    pdir.mkdir(parents=True)
    (pdir / "system_prompt.md").write_text(voice)
    if toml is None:
        toml = (
            'display_name = "Prediction Pulse"\n'
            'handle = "pulse.bsky.social"\n'
            'avatar = "avatar.png"\n'
            'bio = "Data-driven market moves. Not advice."\n'
        )
    (pdir / "persona.toml").write_text(toml)
    return pdir


def test_load_persona_reads_voice_and_identity(tmp_path):
    _write_persona(tmp_path, "alpha")
    p = load_persona("alpha", root=tmp_path)
    assert isinstance(p, Persona)
    assert p.name == "alpha"
    assert p.voice == "You are a witty markets bot."
    assert p.display_name == "Prediction Pulse"
    assert p.handle == "pulse.bsky.social"
    assert p.avatar == "avatar.png"
    assert p.bio.startswith("Data-driven")


def test_channels_default_to_empty(tmp_path):
    _write_persona(tmp_path, "alpha")
    assert load_persona("alpha", root=tmp_path).channels == []


def test_channels_parsed_when_present(tmp_path):
    toml = (
        'display_name = "X"\nhandle = "x"\n'
        '[[channels]]\nplatform = "bluesky"\nhandle = "beta.bsky.social"\n'
        '[[channels]]\nplatform = "mastodon"\ninstance = "https://mastodon.social"\n'
    )
    _write_persona(tmp_path, "beta", toml=toml)
    assert load_persona("beta", root=tmp_path).channels == [
        {"platform": "bluesky", "handle": "beta.bsky.social"},
        {"platform": "mastodon", "instance": "https://mastodon.social"},
    ]


def test_missing_persona_raises_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_persona("nope", root=tmp_path)


# ── channels are validated at the load boundary, like [pipeline.*] ──
# An operator typo must fail when the persona loads, not hours later when a publish cycle first
# reaches the factory.

@pytest.mark.parametrize("block, expected", [
    ('[[channels]]\nplatform = "twiter"\n', "twiter"),                    # typo'd platform
    ('[[channels]]\nplatform = "mastodon"\n', "instance"),                # missing required key
    ('[[channels]]\nplatform = "bluesky"\nhandel = "typo"\n', "handel"),  # typo'd key
])
def test_load_persona_rejects_a_malformed_channel(tmp_path, block, expected):
    _write_persona(tmp_path, "bad", toml=f'display_name = "X"\n{block}')
    with pytest.raises(ValueError, match=expected):
        load_persona("bad", root=tmp_path)


def test_the_real_live_personas_still_load():
    """Tripwire: strict validation must not brick a running supervisor. These are the two personas
    that pulse@gnome and pulse@beanfacts load at startup."""
    for name in ("gnome", "beanfacts", "example"):
        persona = load_persona(name, root="personas")
        assert persona.name == name


def test_channel_handle_prefers_the_personas_bluesky_channel(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    p = Persona(name="x", voice="v",
                channels=[{"platform": "mastodon", "instance": "https://m.example",
                           "handle": "@x@m.example"},
                          {"platform": "bluesky", "handle": "mine.bsky.social"}])
    assert p.channel_handle("bluesky") == "mine.bsky.social"
    assert p.channel_handle("mastodon") == "@x@m.example"


def test_channel_handle_falls_back_to_global_config(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    p = Persona(name="x", voice="v", channels=[])
    assert p.channel_handle("bluesky") == "global.bsky.social"


def test_channel_handle_never_hands_another_platform_the_bluesky_identity(monkeypatch):
    """The bug: the fallback returned BLUESKY_HANDLE for ANY platform, so a Mastodon channel with
    no explicit handle would have acted as the Bluesky account."""
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    p = Persona(name="x", voice="v", channels=[])
    assert p.channel_handle("mastodon") == ""


def test_persona_draft_max_length_is_the_tightest_channel():
    p = Persona(name="x", voice="v",
                channels=[{"platform": "mastodon", "instance": "https://m.example"},
                          {"platform": "bluesky"}])
    assert p.draft_max_length() == 300
