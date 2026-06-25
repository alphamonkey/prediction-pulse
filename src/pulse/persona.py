"""Persona — the brand a writer speaks as: voice (system prompt) + identity + channels.

A persona is authored by the operator as files on disk:
    personas/<name>/system_prompt.md   # the voice (fed to the writer)
    personas/<name>/persona.toml       # display_name, handle, avatar, bio, channels

The writer reads `persona.voice`; the (future) publisher reads `persona.channels`.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pulse.config import PERSONAS_DIR


@dataclass(frozen=True)
class Persona:
    name: str
    voice: str  # the system prompt
    display_name: str | None = None
    handle: str | None = None
    avatar: str | None = None
    bio: str | None = None
    channels: list = field(default_factory=list)  # publisher fills these in later


def load_persona(name: str, *, root: str | Path = PERSONAS_DIR) -> Persona:
    """Load a persona by name from `<root>/<name>/`. Raises FileNotFoundError if absent."""
    pdir = Path(root) / name
    voice = (pdir / "system_prompt.md").read_text().strip()
    meta = tomllib.loads((pdir / "persona.toml").read_text())
    return Persona(
        name=name,
        voice=voice,
        display_name=meta.get("display_name"),
        handle=meta.get("handle"),
        avatar=meta.get("avatar"),
        bio=meta.get("bio"),
        channels=list(meta.get("channels", [])),
    )
