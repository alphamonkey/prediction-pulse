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

from pulse.channels import validate_channels
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
        """The account this persona acts as on `platform` — how publish/engage/metrics decide who
        they speak for. Falls back to that platform's OWN credential default (never another's)."""
        from pulse import channels
        for channel in self.channels:
            if channel.get("platform") == platform:
                return channels.handle_for(channel)
        return channels.channel_spec(platform).handle_default()

    def draft_max_length(self) -> int:
        """How long one draft may be: the tightest limit among the channels it will be fanned out
        to. A persona with no channels keeps Bluesky's historical limit."""
        from pulse import channels
        return channels.draft_max_length(self.channels)


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
        # Strict, like parse_pipeline below: an operator typo fails here, at load, rather than
        # hours later when a publish cycle first reaches the factory.
        channels=validate_channels(meta.get("channels", [])),
        pipeline=parse_pipeline(meta.get("pipeline", {})),
    )
