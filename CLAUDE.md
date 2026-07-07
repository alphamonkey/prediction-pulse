# CLAUDE.md — persona-pulse

> Handoff brief for the next agent. **Live on Bluesky** as a persona fleet (currently one persona:
> gnome). This is the as-built map; decision history is in the agent memory directory (`MEMORY.md`
> index) and `docs/superpowers/specs/`.

## What it is
A platform for running a **fleet of self-contained social bot personas**. A Persona is a container:
it declares its whole stack in `personas/<name>/persona.toml` (`[pipeline.*]` — poll/draft/publish/
engage/metrics; **a job runs iff its section is present**, fields fall back to `config.py`
defaults) and owns its own DB (`data/<name>.db`), secrets (`secrets/<name>.env`, incl. per-persona
`PULSE_MODE`), and process (`pulse supervise <name>` ⇒ systemd `pulse@<name>`).

The first persona posts prediction-market moves: deterministic pipeline detects "interesting"
Kalshi events (selected by Bluesky trends), **Claude writes** in the persona's voice, publishes to
Bluesky behind a pluggable interface. **Moat = data + distribution, not generation.** Deterministic
core; LLM only for the judgment/language task; cheap; measure-before-scale.

## Architecture (as built) — `src/pulse/`
Every stage is a swappable seam (a `Protocol`); the supervisor wires a persona's declared jobs.

- **`persona.py` + `pipeline.py`** — `load_persona()` reads `personas/<name>/{system_prompt.md,
  persona.toml}` → `Persona` (voice/identity/channels + `pipeline: PipelineSpec`).
  `parse_pipeline()` is strict (unknown sections/keys raise); engage `windows = "publish"` aliases
  the persona's publish windows; engage `allow` defaults to its own `queries`.
  `Persona.channel_handle(platform)` picks the acting account (publish/engage/metrics all use it).
- **`supervisor.py`** — `build_supervised()` assembles declared jobs via the existing factories
  (live gates intact) + an always-on daily `PruneJob`; `supervise()` runs each scheduler on a
  thread sharing one SIGTERM-wired stop Event. **Each job gets its OWN DB connection** — sharing
  one across threads broke `wal_checkpoint` live (Database's lock covers writes only; WAL +
  busy_timeout serialize across connections).
- **`venue/`** — `SnapshotSource` seam + **registry** (`registry.py`: name → builder; a new
  content source is one entry). `kalshi.py` (category allowlist + volume floor), `trending.py`
  (`BlueskyTrendSource`: markets matched to Bluesky trends via token co-occurrence — the live
  gnome source; far fewer snapshots than the broad poll).
- **`detector/`** — pure rules via a registry: `odds_swing`, `volume_spike`, `milestone`,
  `new_market` → `Event`s. No LLM, fully TDD.
- **`writer/`** — `Writer` seam + `make_writer()` factory (`writer/factory.py`): `ClaudeWriter`
  (Haiku, cost tracking, cache_control) when `ANTHROPIC_API_KEY` set, else `TemplateWriter`.
  `select.py` ranks events by `RULE_WEIGHTS`.
- **`publish/`, `engage/`, `metrics/`** — `Publisher` / `TargetSource`+`Engager` /
  `EngagementSource` seams, each with a dryrun implementation and a `make_*` **live gate**
  (real adapter only when `PULSE_MODE=live` + creds). Engage: search → relevance/safety filter →
  capped idempotent signals (`interactions` table). Metrics: capability-driven `MetricKind` bag
  (see memory `cross-platform-seams`); latest-only upserts.
- **`store/db.py`** — SQLite + WAL, write lock, `busy_timeout=60s`, `INSERT OR IGNORE`
  idempotency. Tables: `market_snapshots`, `posted_events`, `drafts`, `posts`,
  `account_snapshots`, `post_metrics` (tall), `interactions`. KPM reads: `kpms`,
  `follower_series`, `top_posts`. **No persona column — the DB file is the persona key.**
- **`scheduler/`** — `Job`/`Scheduler` seam; `IntervalScheduler` + `WindowedScheduler`
  (dayparting via pure tz-aware helpers in `windows.py`). Both survive per-cycle exceptions and,
  with `max_iterations`, exit without a trailing sleep.
- **`server/`** — read-only FastAPI **fleet dashboard**: discovers `data/*.db` per request,
  `?persona=` on all routes (unknown → 404), UI persona picker, KPM scorecard + pipeline view +
  live trends widget (TTL-cached; memory `dashboard-external-fetch-ok`).
- **`main.py`** — CLI: `supervise <name>`; one-shots `poll/run/draft/publish/engage/metrics/prune/
  vacuum` (all `--persona`-scoped via `config.db_path_for`); `serve`. `pulse supervise` loads
  `secrets/<name>.env` with override.
- **`config.py`** — the **defaults layer** (persona `[pipeline]` overrides). Env-derived values
  are **lazy accessors** (`pulse_mode()`, `bluesky_handle()`, …) — never import-time bound.
  `PULSE_DB_PATH` pins all personas to one file (escape hatch); `PULSE_DATA_DIR`/`PULSE_SECRETS_DIR`
  relocate the layout.

## Running state
Live: **`pulse@gnome`** (supervisor: `poll:trend` 15m, draft 1h, publish 4h+jitter in ET windows,
engage 1h in-window signals-only, metrics 1h, prune daily) + `prediction-pulse-dashboard` (`:8440`).
Per-stage units are retired (disabled; files removed from `deploy/`). Adding a persona:
`personas/<name>/` + `secrets/<name>.env` + `sudo systemctl enable --now pulse@<name>`.

**Deploy gotchas:** code changes apply on plain `systemctl restart pulse@gnome`; `deploy/*.service`
changes must be re-copied to `/etc/systemd/system/` + `daemon-reload`. **Interactive sudo does not
work in-session** — hand the operator the command block for a separate terminal, then verify with
read-only commands. See memory `deploy-ops`.

## Conventions
- **Never commit `.env`, `secrets/`, or `*.db`.** Real data only — never fabricate numbers. Light
  "not financial advice" framing. No agriculture/food topics.
- **Dry-run first**: new personas keep `PULSE_MODE=dryrun` in their secrets file until copy review.
- **TDD** (tests-first; mock Bluesky/Claude at boundaries). Clean seams. Avoid races (per-job
  connections; WAL + busy_timeout across them).
- **Reach `main` via PR** (gh authed as `alphamonkey`; repo `alphamonkey/persona-pulse`).
  **Stacked-PR gotcha:** merging a stacked PR lands it on its base *branch* — merge bottom-up, or
  a consolidation PR carries the chain to main.
- Personas are the operator's content — don't edit their voice without asking.

## Open items / next work
- Issue #6: API cost on the dashboard. Issue #7: market link per platform. Issue #13: persona
  hot-reload (supervisor is its natural home — persona/policy still load once at startup).
- **New content-source types** (non-market personas) — a `venue/registry.py` entry producing
  normalized snapshots, or a new poll+detect pair emitting `Event`s. A persona scaffolding command.
- **Engagement, deeper:** reply/quote (LLM) actions, reciprocal + curated-list `TargetSource`s,
  tuning dayparting windows from real activity data.
- **Metrics, deeper:** per-post engagement *over time* + rule→engagement attribution (tune
  `RULE_WEIGHTS`). Per-persona isolation is DONE (file-per-persona superseded the old
  `metrics-persona-axis` plan).
- **gnome DB size:** `data/gnome.db` is ~390 MB (never vacuum-converted). One-time
  `pulse vacuum --persona gnome` with `pulse@gnome` stopped will compact + enable incremental
  auto_vacuum; prune alone won't return the space.
- Cross-posting (X / Threads) behind the channel seam.

## Setup
```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev,server]'
mkdir -p secrets && cp deploy/persona.env.example secrets/example.env  # PULSE_MODE=dryrun
.venv/bin/pytest
.venv/bin/pulse supervise example --max-iterations 1   # one dry cycle of every declared job
```
