# persona-pulse: Persona-as-Container design

**Date:** 2026-07-06 · **Status:** approved by operator · **Supersedes:** the single-persona,
globally-configured service layout described in CLAUDE.md as of commit `3f0d612`.

## Why

The project generalizes from "poll Kalshi, post about it" to **a platform for managing social bot
personas**. Today a persona is only voice + identity + channels; every pipeline stage (poll, draft,
publish, engage, metrics) is a *global* systemd service configured by one flat `config.py` + one
`.env`, sharing one SQLite file. That shape cannot host a second persona without collisions on
credentials, storage, policy, and services.

After this change, a **Persona is a container**: it declares its whole stack — content source(s),
drafter, channels/publishers, engagement policy, metrics — and owns its own database, secrets file,
and process. Gnome (live on Bluesky) becomes the first containerized persona and the demo of the
regime. The repo is renamed **persona-pulse** to match the mission.

**Top constraint: no regression.** Gnome is live and healthy; every step must keep it that way.

## Decisions (settled with the operator)

| Concern | Decision |
|---|---|
| Process model | One supervisor process per persona (`pulse supervise <name>`); systemd template unit `pulse@.service`; N personas = N instances of 1 unit file (+ shared dashboard) |
| Storage | One SQLite DB per persona: `data/<name>.db` (gitignored). Schema unchanged — the filename is the persona key. Cross-persona snapshot duplication accepted (~25 MB/persona steady state) |
| Secrets | Per-persona gitignored `secrets/<name>.env` (BLUESKY_*, ANTHROPIC_API_KEY, PULSE_MODE — a new persona can be dryrun while others are live). systemd: `EnvironmentFile=…/secrets/%i.env`; CLI: dotenv |
| Dashboard | Single service; discovers `data/*.db`; `?persona=` on all API routes + UI selector. Fleet-overview page deferred |
| Repo rename | Last, separate PR: `alphamonkey/prediction-pulse` → `alphamonkey/persona-pulse`. Python package/CLI stays `pulse`; new unit names (`pulse@`) are repo-name-agnostic from birth |

## Architecture

### 1. `persona.toml` declares the stack

`persona.toml` keeps voice/identity/channels and gains `[pipeline.*]` sections. **A job runs iff
its section is present** (nothing is hard-required; a metrics-only lurker persona is legal).
Omitted fields fall back to `config.py`, which becomes the *defaults* layer rather than the policy
layer. Gnome's, mirroring current live cadences:

```toml
[pipeline.poll]
sources = ["trend"]        # resolved via the source registry: "kalshi" | "trend" | future
interval = 900

[pipeline.draft]
interval = 3600
limit = 9

[pipeline.publish]
interval = 14400
jitter = 600
windows = [["07:00", "10:00"], ["12:00", "14:00"], ["17:00", "22:00"]]
tz = "America/New_York"

[pipeline.engage]
interval = 3600
jitter = 600
windows = "publish"        # alias: reuse the publish windows
queries = ["kalshi", "prediction market", "polymarket"]
actions = ["like", "repost"]
# allow / deny / caps — everything the engage policy reads from global config today

[pipeline.metrics]
interval = 3600
```

Parsed into a frozen `PipelineSpec` dataclass (per-job sub-specs); `Persona` grows a `pipeline`
field. Writer/publisher consumers are untouched. Detector thresholds and `RULE_WEIGHTS` stay global
defaults for now (per-persona overrides are a later, additive step).

### 2. Source registry

A name → builder mapping (`"kalshi"`, `"trend"`) replaces the `_make_source` if/else.
`[pipeline.poll] sources = [...]` resolves through it. This is the groundwork for "get *something*
to tweet about": a future news/RSS source for a non-market persona is a registry entry producing
`Event`s, not a rewrite.

### 3. Supervisor: one process per persona

`supervisor.py` + `pulse supervise <name>`: opens `data/<name>.db`, builds each declared job via
the existing factories (live gates intact), wraps each in its existing scheduler
(`WindowedScheduler` for publish/engage, `IntervalScheduler` otherwise), runs each scheduler on a
thread sharing one stop `Event` wired to SIGINT/SIGTERM. The schedulers are already interruptible
and per-cycle-exception-proof, so this is assembly, not new machinery.

- **Prune folds in:** the supervisor schedules `PruneJob` daily per persona; the standalone prune
  timer/service retires.
- **Metrics becomes persona-aware:** `MetricsJob`'s handle comes from `persona.channels` (mirroring
  `PublishJob`) instead of global `BLUESKY_HANDLE` — closing the known metrics-persona-axis gap.

### 4. Config lazification (prerequisite)

`config.py` binds env vars at import time, which breaks runtime per-persona env loading (and
already breaks `test_defaults_to_dryrun` now that the real `.env` is live). The ~5 env-derived
values (PULSE_MODE, BLUESKY_HANDLE, BLUESKY_APP_PASSWORD, ANTHROPIC_API_KEY, DB path) become lazy
accessor functions reading `os.environ` at call time. Pure tunables stay constants.

### 5. systemd: 2 unit files, N+1 instances

```ini
# deploy/pulse@.service (template)
ExecStart=…/pulse supervise %i
EnvironmentFile=…/secrets/%i.env
```

Adding a persona = `persona.toml` + `secrets/<name>.env` + `systemctl enable --now pulse@<name>`.
Per-persona restart and logs (`journalctl -u pulse@gnome`). The six per-stage units retire.

## Migration (gnome stays live)

1. Ship all code; old services keep running unchanged (old CLI paths preserved during transition).
2. Write gnome's `[pipeline]` + `secrets/gnome.env` from the current `.env`.
3. Cutover: stop old services → WAL-checkpoint + `mv prediction_pulse.db data/gnome.db` → install
   `pulse@.service` → `systemctl enable --now pulse@gnome` → verify (journalctl + dashboard) →
   retire old units. Minutes of downtime; rollback = move the file back, restart old units.

## Non-goals (this milestone)

New source types beyond Kalshi; persona scaffolding tooling; reply/quote engagement; cross-posting;
persona hot-reload (issue #13 — the supervisor is its natural future home, not built now).

## Testing

TDD throughout; Bluesky/Claude mocked at their boundaries. Key surfaces: spec parsing, supervisor
job assembly against fakes, lazy-config accessors, dashboard `?persona=` routing. End-to-end dryrun:
`pulse supervise <temp persona> --max-iterations 1` exercises every declared job against a temp DB
with dry-run/null adapters and a template writer — no live creds needed.
