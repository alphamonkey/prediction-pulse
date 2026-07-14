# CLAUDE.md — persona-pulse

> Handoff brief for the next agent. **Live on Bluesky** as a two-persona fleet (`gnome`,
> `beanfacts`). This is the as-built map; decision history is in the agent memory directory
> (`MEMORY.md` index) and `docs/superpowers/specs/`.

## What it is
A platform for running a **fleet of self-contained social bot personas**. A Persona is a container:
it declares its whole stack in `personas/<name>/persona.toml` (`[pipeline.*]` — poll/draft/publish/
engage/metrics; **a job runs iff its section is present**, fields fall back to `config.py`
defaults), its **channels** (`[[channels]]` — the accounts it acts as), and owns its own DB
(`data/<name>.db`), secrets (`secrets/<name>.env`, incl. per-persona `PULSE_MODE`), and process
(`pulse supervise <name>` ⇒ systemd `pulse@<name>`).

Two personas run today: **`gnome`** posts prediction-market moves (deterministic pipeline detects
"interesting" Kalshi events, selected by Bluesky trends), and **`beanfacts`** posts invented bean
"facts" from operator-authored topic seeds with no external input at all. In both, **Claude writes**
in the persona's voice and the post is published behind a pluggable interface.
**Moat = data + distribution, not generation.** Deterministic core; LLM only for the
judgment/language task; cheap; measure-before-scale.

## Architecture (as built) — `src/pulse/`
Every stage is a swappable seam (a `Protocol`); the supervisor wires a persona's declared jobs.

- **`persona.py` + `pipeline.py` + `channels.py`** — `load_persona()` reads
  `personas/<name>/{system_prompt.md, persona.toml}` → `Persona` (voice/identity/channels +
  `pipeline: PipelineSpec`). Both `parse_pipeline()` and `validate_channels()` are **strict**
  (unknown sections/keys/platforms raise **at load**, not hours later at the factory); engage
  `windows = "publish"` aliases the persona's publish windows; engage `allow` defaults to its own
  `queries`. `Persona.channel_handle(platform)` picks the acting account **per platform** — it
  never falls back to another platform's identity.
- **`channels.py` — the channel registry.** Pure data + validation; it never constructs an adapter,
  which is the point: the writer needs a platform's `max_length` before any Publisher exists, and
  `load_persona` must reject a bad `[[channels]]` block without credentials. One `ChannelSpec` per
  platform (limit, engage actions, required/optional keys). `Persona.draft_max_length()` is the
  **minimum** across the persona's channels — one draft is fanned out to all of them, so it must fit
  the tightest, or the strictest publisher truncates copy the writer thought it had room for.
- **`supervisor.py`** — `build_supervised()` assembles declared jobs via the existing factories
  (live gates intact) + an always-on daily `PruneJob`; `supervise()` runs each scheduler on a
  thread sharing one SIGTERM-wired stop Event. **Each job gets its OWN DB connection** — sharing
  one across threads broke `wal_checkpoint` live (Database's lock covers writes only; WAL +
  busy_timeout serialize across connections).
- **`venue/`** — `ContentSource` seam ("produce this cycle's newly recorded `Event`s"; sources
  record via `db.record_posted`, whose INSERT OR IGNORE backstops races) + **registry**
  (`registry.py`: `SourceSpec` → builder; builders validate their own option keys and pull deps
  from a lazy `SourceContext` — no market sources ⇒ no Kalshi client). Market polling is one
  implementation: `SnapshotContentSource` wraps a `SnapshotSource` (fetch → store → detect).
  Sources: `kalshi.py` (category allowlist + volume floor), `trending.py` (`BlueskyTrendSource`:
  markets matched to Bluesky trends — the live gnome source), `generator.py` (**no external
  input**: emits operator-authored topic seeds; the writer invents the post; bucket-stable dedup;
  options `topics`/`count`/`bucket` via `[[pipeline.poll.source]]` tables — `sources = [...]`
  stays as sugar).
- **`detector/`** — pure rules via a registry: `odds_swing`, `volume_spike`, `milestone`,
  `new_market` → `Event`s. No LLM, fully TDD. `Event` is the universal content unit: non-market
  events carry `value_kind=None` + `context.source_kind` (the persisted discriminator — only
  rule/headline/dedup_key are load-bearing downstream).
- **`writer/`** — `Writer` seam + `make_writer()` factory (`writer/factory.py`): `ClaudeWriter`
  (Haiku, cost tracking, cache_control) when `ANTHROPIC_API_KEY` set, else `TemplateWriter`.
  `select.py` ranks events by `RULE_WEIGHTS`.
- **`publish/`, `engage/`, `metrics/`** — `Publisher` / `TargetSource`+`Engager` /
  `EngagementSource` seams, each with a dryrun implementation and a `make_*` **live gate** (real
  adapter only when `PULSE_MODE=live` + creds). All three factories take a **channel dict** and are
  the same shape; **all three jobs loop `persona.channels`**. Capabilities are declared, not
  assumed: `Publisher.max_length`, `Engager.supported_actions`, `EngagementSource.supported_metrics`
  — so a platform that can't do something simply doesn't list it (see memory
  `cross-platform-seams`). Channels: **bluesky** (atproto SDK) and **mastodon** (`mastodon.py`, a
  thin shared httpx client — no SDK exists; instance-agnostic, so it also serves Pleroma/Akkoma/
  GoToSocial). Engage: search → relevance/safety filter → capped idempotent signals (`interactions`);
  a known platform with no `TargetSource` gets `NullTargetSource` (finds nothing) so a new channel
  can't take a live persona's engage job down. Metrics: latest-only upserts.
- **`store/db.py`** — SQLite + WAL, write lock, `busy_timeout=60s` (set **first**, before any pragma
  that can contend), `INSERT OR IGNORE` idempotency. Tables: `market_snapshots`, `posted_events`,
  `drafts`, `posts`, `account_snapshots`, `post_metrics` (tall), `interactions`. KPM reads: `kpms`,
  `follower_series`, `top_posts` — **single-platform by construction** (default: the most recently
  snapshotted), because two accounts' follower counts in one series describe neither.
  **No persona column — the DB file is the persona key**; `platform`/`channel` IS a column, since one
  persona has many accounts. `_migrate()` is additive, idempotent, and race-safe (the supervisor
  opens one connection per job).
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
Live, both on Bluesky: **`pulse@gnome`** (`poll:trend` 15m, draft 1h, publish 4h+jitter in ET
windows, engage 1h in-window signals-only, metrics 1h, prune daily) and **`pulse@beanfacts`**
(`poll:generator` 1h, same publish/engage/metrics cadence; live since 2026-07-09) +
`persona-pulse-dashboard` (`:8440`). Per-stage units are retired (disabled; files removed from
`deploy/`).

**Adding a persona:** `personas/<name>/` + `secrets/<name>.env` + `sudo systemctl enable --now
pulse@<name>`.
**Adding a channel to an existing persona:** a `[[channels]]` block in its `persona.toml` + the
platform's secret in `secrets/<name>.env`. **That's the whole change — no code.** (Enforced by
`tests/test_multichannel_acceptance.py`, whose two runs differ only by a TOML string.)

**Deploy gotchas:** code changes apply on plain `systemctl restart pulse@<name>`; `deploy/*.service`
changes must be re-copied to `/etc/systemd/system/` + `daemon-reload`. **Interactive sudo does not
work in-session** — hand the operator the command block for a separate terminal, then verify with
read-only commands. See memory `deploy-ops`. **Restart the supervisors BEFORE the dashboard** after
a schema change: `connect_readonly` never migrates, so the dashboard would read a pre-migration DB.
**You cannot force a dry run** — `pulse supervise` loads the persona's secrets with `override=True`,
so `PULSE_MODE=dryrun` on the command line is silently ignored (issue #40; memory
`dryrun-cannot-be-forced`). Check the `mode=` in the log before trusting a "dry" run.

## Conventions
- **Never commit `.env`, `secrets/`, or `*.db`.** For **market personas**: real data only —
  never fabricate numbers; light "not financial advice" framing; no agriculture/food topics
  (enforced in the Kalshi category allowlist). Generator personas may be fabrication-by-design
  (e.g. the planned Bean Facts), but their fiction must be obvious — never fake *market* data.
- **Dry-run first**: new personas keep `PULSE_MODE=dryrun` in their secrets file until copy review.
  (A new *channel* on an already-live persona can't be dry-run today — issue #40.)
- **TDD** (tests-first; mock Bluesky/Mastodon/Claude at boundaries — each test file defines its own
  fakes; there are no shared ones). Clean seams. Avoid races (per-job connections; WAL +
  busy_timeout across them). **Tests must never spend money**: `conftest.py` unsets
  `ANTHROPIC_API_KEY` for every test, because `config` loads the repo's real `.env` at import.
- **Reach `main` via PR** (gh authed as `alphamonkey`; repo `alphamonkey/persona-pulse`).
  **Stacked-PR gotcha:** merging a stacked PR lands it on its base *branch* — merge bottom-up, or
  a consolidation PR carries the chain to main.
- Personas are the operator's content — don't edit their voice without asking.

## Open items / next work
- Issue #6: API cost on the dashboard. Issue #7: market link per platform (now a **per-channel**
  decision — see the platform notes below). Issue #13: persona hot-reload (supervisor is its
  natural home — persona/policy still load once at startup). Issue #40: no way to force a dry run.
- **Mastodon go-live** (the channel seam is DONE and tested; nothing is live on it yet). Operator
  prerequisites, none of them code: pick a bot-tolerant instance, create one account per persona,
  **set each profile's bot flag** (the pipeline does NOT push profile metadata — memory
  `persona-profile-not-pushed`), put each token in `secrets/<persona>.env`, then add the
  `[[channels]]` block. NB: adding a channel to a live persona publishes to it **immediately** (a
  global `PULSE_MODE` was a deliberate choice), and the first cycle can back-post up to a day of
  eligible drafts — review copy first.
- **Platform decisions (recorded, revisit only if the facts change).** The seam doesn't preclude
  either, but neither is worth building today:
  - **X/Twitter — rejected on economics + policy.** No free tier since Feb 2026: pay-per-use at
    $0.015/post and **$0.20 per post containing a URL** (13×, which lands squarely on issue #7).
    Its automation rules *prohibit* automated likes and follows outright and restrict replies to
    "user engaged first," so a persona's whole growth engine is off the table there.
  - **Truth Social — rejected on ToS.** §4.6 forbids accessing the service "through automated or
    non-human means, whether through a bot, script, or otherwise"; no developer API exists. (It is
    a reskinned Mastodon fork, so our adapter would *technically* speak its API. Don't.)
  - **Threads** — free official API and automation is explicitly permitted; the cost is calendar
    time (Meta App Review: screencast, privacy policy, business verification). The plausible third
    channel.
- **Engagement, deeper:** reply/quote (LLM) actions + follow (issue #38 — likes/reposts alone
  converted 462 outbound signals into 9 followers), reciprocal + curated-list `TargetSource`s,
  tuning dayparting windows from real activity data.
- **Metrics, deeper:** per-post engagement *over time* + rule→engagement attribution (tune
  `RULE_WEIGHTS`). Per-persona isolation is DONE (file-per-persona superseded the old
  `metrics-persona-axis` plan); per-**platform** isolation is DONE (`account_snapshots.platform`).
- **Content sources:** externally-fed non-market sources (news/weather/RSS) and a persona
  scaffolding command. The content-source seam is DONE (spec:
  `docs/superpowers/specs/2026-07-09-generator-content-source-design.md`).
- **Known dashboard gap:** the UI has no channel picker yet — `/api/kpms`, `/api/followers` take
  `?platform=` and `/api/platforms` lists them, but the page still renders the default (most
  recent) platform only. Wire the picker when a persona actually has two channels.

## Setup
```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev,server]'
mkdir -p secrets && cp deploy/persona.env.example secrets/example.env  # PULSE_MODE=dryrun
.venv/bin/pytest
.venv/bin/pulse supervise example --max-iterations 1   # one dry cycle of every declared job
```
