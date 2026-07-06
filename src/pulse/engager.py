"""The engage cycle: find targets → filter → act (signals) → record — idempotently, under caps.

The outbound-action counterpart to publisher.py. Targets come from a swappable `TargetSource`
(topical search now); actions go through a capability-declaring `Engager` behind the live gate
(`make_engager`). Dryrun-safe: the DryRunEngager performs nothing and records nothing, so flipping
to live engages fresh. Mirrors drafter.py / publisher.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pulse import config
from pulse.engage.base import Engager, SignalKind, TargetSource
from pulse.engage.factory import make_engager, make_target_source
from pulse.engage.filter import filter_targets
from pulse.persona import Persona
from pulse.store.db import Database

log = logging.getLogger("pulse")


@dataclass
class EngagePolicy:
    """What to engage with and how much. Built from config by the CLI/service."""

    allow: list[str] = field(default_factory=list)   # relevance filter (keep if matches)
    deny: list[str] = field(default_factory=list)    # safety filter (drop if matches)
    actions: tuple[SignalKind, ...] = (SignalKind.LIKE,)  # enabled actions, attempted in order
    caps: dict[SignalKind, int] = field(default_factory=dict)  # per-action rolling-24h cap
    queries: list[str] = field(default_factory=list)  # Bluesky search terms for the target source


@dataclass
class EngageReport:
    targets: int = 0     # targets considered (after filtering)
    performed: int = 0   # actions actually taken (live)
    would: int = 0       # actions that would be taken (dryrun)
    skipped: int = 0     # actions skipped (cap / already done / unsupported)


def engage_once(
    db: Database, source: TargetSource, engager: Engager, persona: Persona, policy: EngagePolicy,
    *, limit: int, self_handles: tuple[str, ...] = (),
) -> EngageReport:
    channel = engager.name
    # Self is never a valid target (for now and always) — our own handle is excluded before any
    # relevance/safety judgement, so we can't like/repost/follow ourselves.
    targets = filter_targets(
        source.find_targets(limit=limit),
        allow=policy.allow, deny=policy.deny, exclude_handles=self_handles,
    )
    report = EngageReport(targets=len(targets))
    for target in targets:
        for action in policy.actions:
            if action not in engager.supported_actions:
                report.skipped += 1
                continue
            # likes/reposts are keyed on the post uri; follows on the author did.
            if action is SignalKind.FOLLOW:
                check = {"target_did": target.author_did}
                store = {"target_uri": "", "target_did": target.author_did}
            else:
                check = {"target_uri": target.uri}
                store = {"target_uri": target.uri, "target_did": target.author_did}
            if db.has_interacted(persona.name, channel, action, **check):
                report.skipped += 1
                continue
            if db.signals_today(channel, action) >= policy.caps.get(action, 0):
                report.skipped += 1
                continue
            result = engager.engage(target, action)
            if result.performed:
                db.record_interaction(persona.name, channel, action, **store)
                report.performed += 1
            else:
                report.would += 1
    return report


class EngageJob:
    """The engage cycle as a schedulable Job — loops a persona's channels (mirrors PublishJob)."""

    name = "engage"

    def __init__(self, db: Database, persona: Persona, policy: EngagePolicy, *, limit: int) -> None:
        self._db = db
        self._persona = persona
        self._policy = policy
        self._limit = limit

    def run(self) -> EngageReport:
        agg = EngageReport()
        if not self._persona.channels:
            log.warning("persona %s has no channels — nothing to engage", self._persona.name)
        for channel in self._persona.channels:
            source = make_target_source(channel, self._policy)
            engager = make_engager(channel)
            self_handle = channel.get("handle") or config.bluesky_handle()
            r = engage_once(self._db, source, engager, self._persona, self._policy,
                            limit=self._limit, self_handles=(self_handle,))
            agg.targets += r.targets
            agg.performed += r.performed
            agg.would += r.would
            agg.skipped += r.skipped
        log.info("engage complete (persona=%s): %d performed, %d would, %d skipped (%d targets)",
                 self._persona.name, agg.performed, agg.would, agg.skipped, agg.targets)
        return agg
