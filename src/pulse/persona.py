"""Persona — the brand a writer speaks as, and the container that declares its stack.

A persona is authored by the operator as files on disk:
    personas/<name>/system_prompt.md   # the voice (fed to the writer)
    personas/<name>/persona.toml       # display_name, handle, avatar, bio, channels, [pipeline.*]

The writer reads `persona.voice`; the publisher reads `persona.channels`; the supervisor reads
`persona.pipeline` (which jobs to run, on what cadence/policy — see pulse.pipeline).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from pulse.config import PERSONAS_DIR
from pulse.pipeline import PipelineSpec, parse_pipeline


@dataclass(frozen=True)
class Persona:
    name: str
    voice: str  # the system prompt
    display_name: str | None = None
    handle: str | None = None
    avatar: str | None = None
    bio: str | None = None
    channels: list = field(default_factory=list)  # publisher fills these in later
    pipeline: PipelineSpec = field(default_factory=PipelineSpec)  # the stack this persona runs

    def channel_handle(self, platform: str = "bluesky") -> str:
        """The persona's own handle on a platform, falling back to the global credential
        handle (how PublishJob/MetricsJob decide which account they speak for)."""
        for channel in self.channels:
            if channel.get("platform") == platform and channel.get("handle"):
                return channel["handle"]
        from pulse import config
        return config.bluesky_handle()


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
        pipeline=parse_pipeline(meta.get("pipeline", {})),
    )
