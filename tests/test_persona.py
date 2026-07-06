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
    toml = 'display_name = "X"\nhandle = "x"\nchannels = ["bluesky"]\n'
    _write_persona(tmp_path, "beta", toml=toml)
    assert load_persona("beta", root=tmp_path).channels == ["bluesky"]


def test_missing_persona_raises_clearly(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_persona("nope", root=tmp_path)


def test_channel_handle_prefers_the_personas_bluesky_channel(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    p = Persona(name="x", voice="v",
                channels=[{"platform": "x", "handle": "elsewhere"},
                          {"platform": "bluesky", "handle": "mine.bsky.social"}])
    assert p.channel_handle("bluesky") == "mine.bsky.social"


def test_channel_handle_falls_back_to_global_config(monkeypatch):
    monkeypatch.setenv("BLUESKY_HANDLE", "global.bsky.social")
    p = Persona(name="x", voice="v", channels=[])
    assert p.channel_handle("bluesky") == "global.bsky.social"
