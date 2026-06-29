# CLAUDE.md — prediction-pulse

> Handoff brief for the next agent. The MVP is **built and running live on Bluesky**. This is the
> as-built map; deeper decision history is in the agent memory directory (`MEMORY.md` index).

## What it is
A faceless, data-driven prediction-market content bot. A **deterministic pipeline** detects
"interesting" Kalshi events; **Claude writes** a punchy, accurate post in a persona's voice; it
**publishes to Bluesky** behind a pluggable interface (X / Threads / Mastodon later). Goal: validate
that data-driven prediction-market content gets organic pull — measure engagement, iterate.
Monetization is deferred until traction.

**Moat = data + distribution, not generation.** Deterministic core; the LLM does only the
judgment/language task; cheap; measure-before-scale.

## Architecture (as built) — `src/pulse/`
Every stage is a swappable seam (a `Protocol`); the orchestrators wire them together.

- **`venue/`** — `SnapshotSource` seam. `kalshi.py`: `KalshiClient` (httpx, free public API,
  category allowlist + 24h-volume floor) + `KalshiSource` → normalized `Snapshot`s.
- **`detector/`** — pure rules over recent snapshots, via a rule registry: `odds_swing`, `volume_spike`,
  `milestone`, `new_market`. Emits `Event`s. No LLM, fully TDD.
- **`models.py`** — `Snapshot`, `Event`, `MarketMeta`, `ValueKind`.
- **`writer/` + `persona.py`** — `Writer` seam + `Draft`. `ClaudeWriter` (Haiku, `WriterUsage` cost
  tracking, cache_control) when `ANTHROPIC_API_KEY` set, else `TemplateWriter`. `select.py` ranks
  events by `RULE_WEIGHTS`. `load_persona()` reads `personas/<name>/{system_prompt.md,persona.toml}`
  (voice + `channels`). `make_writer()` lives in `main.py`.
- **`publish/` + `publisher.py`** — `Publisher` seam + `PostResult`. `BlueskyPublisher` (atproto,
  lazy login, 300-grapheme cap), `DryRunPublisher` (logs, posts nothing). `make_publisher()` is the
  **live gate** (real publisher only when `PULSE_MODE=live` + creds, else DryRun). `publish_once` +
  `PublishJob` post a persona's freshest, non-stale, un-posted drafts per channel — idempotent, under
  the daily cap.
- **`metrics/`** — `EngagementSource` seam (mirrors `publish/`): `BlueskyEngagementSource` (atproto,
  read-only, batches `get_posts` by 25), `NullEngagementSource`, `make_engagement_source()` live
  gate. Capability-driven over a normalized `MetricKind` vocabulary + per-post metric *bag*, so
  platforms with different metric sets (Bluesky vs. X's impressions/bookmarks) slot in with no
  schema/UI change (see memory `cross-platform-seams`). `collect_once` + `MetricsJob` snapshot the
  account + upsert recent posts' current engagement — latest-only, no per-post time-series.
- **`store/db.py`** — SQLite + WAL, `threading.Lock`, `busy_timeout=60s`, `INSERT OR IGNORE`
  idempotency. Tables: `market_snapshots`, `posted_events`, `drafts`, `posts`, `account_snapshots`
  (follower series), `post_metrics` (tall: one row per uri+metric → new metrics need no `ALTER`).
  KPM reads: `kpms`, `follower_series`, `top_posts`.
- **`scheduler/`** — `Job`/`Scheduler` seam + `IntervalScheduler` (interruptible `stop.wait`,
  `max_iterations`, optional `jitter_seconds`; survives per-cycle exceptions). `WindowedScheduler`
  adds **dayparting**: same interval cadence but only inside active windows (pure tz-aware helpers in
  `scheduler/windows.py`), sleeping toward the next window otherwise. Publisher + engager run
  windowed (`PUBLISH_WINDOWS`/`ENGAGE_WINDOWS`/`ACTIVE_TZ`); poller/drafter/metrics stay 24/7.
- **`engage/` + `engager.py`** — outbound *Action* seam (sibling of `publish/`): `TargetSource`
  (`TopicalSearchSource` over Bluesky search) → relevance/safety filter → `Engager`
  (`BlueskySignalEngager` like/repost/follow, `DryRunEngager`, `make_engager` live gate). `engage_once`
  + `EngageJob` act on a persona's channels under per-action caps + `interactions`-table idempotency.
  Signals only for now (reply/quote reserved); follows off by default.
- **`poller.py` / `drafter.py`** — the collect and draft cycles as `Job`s (`PollJob`, `DraftJob`).
- **`server/`** — read-only FastAPI dashboard (`app.py` + `static/`), per-request `connect_readonly`.
  Leads with a KPM **scorecard** (`/api/kpms|followers|top-posts`) over the **Pipeline** throughput
  view (`/api/stats|events|drafts`).
- **`main.py`** — CLI: `poll`, `run`, `draft`, `publish`, `engage`, `metrics`, `serve` (see README).
- **`config.py`** — all knobs. `.env` (never committed) supplies `PULSE_MODE`, `BLUESKY_*`,
  `ANTHROPIC_API_KEY`.

## Running state
Live on Bluesky. systemd services (`deploy/`): poller `prediction-pulse` (15 min), drafter
`prediction-pulse-drafter` (1 h), publisher `prediction-pulse-publisher` (4 h + jitter), engager
`prediction-pulse-engager` (1 h + jitter, signals only), metrics `prediction-pulse-metrics`
(1 h + jitter, read-only/no-op in dryrun), dashboard `prediction-pulse-dashboard` (`:8440`).
**Publisher + engager are dayparted** (act only inside `ACTIVE_TZ` windows); the rest run 24/7.
Dry-run until `PULSE_MODE=live` in `.env`.

**Deploy gotcha:** code changes apply on a plain `systemctl restart`; **`deploy/*.service` changes
must be re-copied** to `/etc/systemd/system/` + `daemon-reload` + restart (git pull doesn't do it).
The operator runs `sudo` via the `!` prefix (no passwordless sudo). See memory `deploy-ops`.

## Conventions
- **Never commit `.env` or `*.db`.** Real data only — never fabricate numbers. Light "not financial
  advice" framing. No agriculture/food topics.
- **Dry-run first**, review copy, then flip `PULSE_MODE=live`.
- **TDD** (tests-first; mock Bluesky/Claude at their boundaries). Clean architecture / swappable
  seams. Avoid races (single-writer lock + busy_timeout).
- **Reach `main` via PR**, not local merge (gh is authed as `alphamonkey`; repo
  `alphamonkey/prediction-pulse`). Reuse from sibling repos (`kalshi-edge`, `kalshi-bot`) only when
  it keeps the build clean.
- Personas are the operator's content — don't edit their voice without asking.

## Open items / next work
- Issue #6: surface API cost on the dashboard. Issue #7: attach the market link per platform.
  Issue #13: hot-reload persona (persona/policy load once at daemon startup → voice/config edits
  currently need a service restart).
- **Snapshot retention/pruning + DB bloat — top operational risk.** `market_snapshots` grows
  unbounded and the `*.db-wal` has ballooned (~2.4 GB seen, checkpoints starving) — the real cause
  behind past lock contention / slowing poll cycles. Its own chunk.
- A **new detector type** (operator is designing it). A **reverse-poller** (Bluesky trending →
  matching Kalshi market) — plugs in as another engagement `TargetSource` and/or feeds original
  posts. Cross-posting (X / Threads).
- **Engagement, deeper:** signals (like/repost/follow) ship via `engage/` behind dayparting; still
  open are reciprocal + curated-list `TargetSource`s, reply/quote (LLM) actions, and **tuning the
  dayparting windows from real activity data**.
- **Engagement pull-back, deeper layer:** the `metrics/` seam now collects *current aggregate*
  engagement for the KPM dashboard; still open are per-post engagement *over time* and
  rule→engagement *attribution* (which rule travels best → tune `RULE_WEIGHTS`).
- **Persona/channel-aware metrics:** the metrics layer is currently single-account/global
  (`account_snapshots` has no persona key; the collector uses one `BLUESKY_HANDLE` and doesn't loop
  `persona.channels`; reads aggregate everything). For concurrent personae this blurs into one
  series. Extension path (no architectural rework — persona is the one missing axis): persona/handle
  dimension on `account_snapshots`, collector loops `persona.channels` (mirror `PublishJob`),
  optional persona/channel filters on the reads + a dashboard selector. See memory
  `metrics-persona-axis`.

## Setup
```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev,server]'
cp .env.example .env   # Bluesky + Anthropic; PULSE_MODE=dryrun to start
.venv/bin/pytest
```
