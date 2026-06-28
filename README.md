# prediction-pulse

A faceless, data-driven **prediction-market content engine**. A deterministic pipeline detects
interesting prediction-market events (odds swings, volume spikes, round-number milestones, notable
new markets) from free Kalshi data; Claude writes a punchy, accurate post in a persona's voice; and
it publishes to **Bluesky** behind a pluggable interface (X / Threads / Mastodon drop in later).

The point isn't generating text — anyone can do that. It's owning a **data → insight → distribution**
pipeline in a niche where the data is genuinely shareable, and measuring what travels before
spending on scale or chasing monetization.

> **Status: MVP complete and running live on Bluesky.** The full pipeline (collect → detect → draft
> → publish) plus a monitoring dashboard run as systemd services. It is **dry-run by default** — it
> only posts when `PULSE_MODE=live`.

## Pipeline

Each stage is a swappable seam (a `Protocol`), so new venues, writers, publishers, or schedules drop
in without touching the rest:

```
Kalshi poller ──▶ detector ──▶ Claude writer ──▶ Bluesky publisher
(SnapshotSource)  (rule        (persona voice)    (Publisher seam)
                   registry)
        └──────────────▶ SQLite (WAL) ◀──────────────┘
                              │
                       read-only dashboard
```

- **`detector/`** — pure, deterministic rules over normalized snapshots (odds swings, volume spikes,
  milestones, new markets). No LLM. TDD.
- **`venue/`** — the `SnapshotSource` seam; `KalshiSource` over the free public API (read-only).
- **`writer/` + `persona.py`** — turns a detected event into a post. `ClaudeWriter` (Haiku, cheap)
  when an API key is set, else a zero-cost `TemplateWriter`. Personas supply the voice + channels.
- **`publish/` + `publisher.py`** — the `Publisher` seam; `BlueskyPublisher` (atproto) in live mode,
  `DryRunPublisher` otherwise. Idempotent (never double-posts), rate-capped, freshest-first.
- **`metrics/`** — the `EngagementSource` seam; pulls platform engagement back into the store for
  the KPM dashboard. Capability-driven over a normalized `MetricKind` vocabulary, so platforms with
  different metric sets (Bluesky vs. X) slot in without schema or UI churn. Read-only; no-op
  outside live mode.
- **`store/`** — SQLite + WAL: snapshots, detected-event log, drafts, posts, account snapshots,
  per-post metrics.
- **`scheduler/`** — the `Job`/`Scheduler` seam; `IntervalScheduler` drives any job on a cadence
  (with optional `--jitter`).
- **`server/`** — read-only FastAPI dashboard (no build step; CDN Tailwind + Chart.js). Leads with a
  KPM **scorecard** (followers + growth, applause / conversation / amplification rates, top-posts
  leaderboard) over a **Pipeline** section (snapshot/event/draft throughput).

## CLI

```
pulse poll                          # one poll+detect cycle, then exit (no publish)
pulse run     [--interval --jitter] # poll+detect on a cadence
pulse draft   [--persona --limit --interval --jitter]   # write drafts for top recent events
pulse publish [--persona --limit --interval --jitter]   # post a persona's freshest drafts
pulse metrics [--limit --interval --jitter]             # collect engagement back for the dashboard
pulse serve   [--host --port]       # the monitoring dashboard
```

`draft`/`publish` are dry-run until `PULSE_MODE=live`; `--interval 0` (default) means one-shot.

## Services (systemd, `deploy/`)

| Service | Command | Cadence |
| --- | --- | --- |
| `prediction-pulse` | `pulse run` | 15 min |
| `prediction-pulse-drafter` | `pulse draft` | 1 h |
| `prediction-pulse-publisher` | `pulse publish` | 4 h (+jitter) |
| `prediction-pulse-metrics` | `pulse metrics` | 1 h (+jitter) |
| `prediction-pulse-dashboard` | `pulse serve` | — (`:8440`) |

All stay dry-run until `PULSE_MODE=live` in `.env`. **Changing a `deploy/*.service` file requires
re-copying it to `/etc/systemd/system/` + `daemon-reload` + restart — `git pull` alone doesn't apply
unit changes** (code changes do apply on a plain restart).

## Personas

Operator-authored under `personas/<name>/`: a `system_prompt.md` (the voice) and a `persona.toml`
(identity + `channels`). Select with `PULSE_PERSONA` or `--persona`. Example:

```toml
display_name = "..."
[[channels]]
platform = "bluesky"
handle = "you.bsky.social"   # optional; falls back to BLUESKY_HANDLE
```

## Setup

```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev,server]'
cp .env.example .env   # Bluesky app password + Anthropic key; PULSE_MODE=dryrun to start
.venv/bin/pytest
```

Most knobs live in `src/pulse/config.py` (cadences, `MAX_POSTS_PER_DAY`, detector thresholds,
`RULE_WEIGHTS`, persona). Credentials and `PULSE_MODE` come from `.env` (never committed).

## Conventions

- **Real data only — never fabricate numbers.** Light "not financial advice" framing; no
  agriculture/food topics.
- **Dry-run first** — review generated posts before flipping `PULSE_MODE=live`.
- **TDD**, deterministic core, LLM only for the language task. Reach `main` via PR.

## Next / open

- Surface API cost on the dashboard (issue #6) and attach the market link per platform (issue #7).
- Snapshot **retention/pruning** (the table grows unbounded, slowly slowing poll cycles).
- A new detector type (in design) and cross-posting to X / Threads.
- **Engagement pull-back, deeper:** per-post engagement *over time* + rule→engagement attribution
  (which detector rule travels best → tune `RULE_WEIGHTS`). The `metrics/` seam now collects current
  aggregates; the time-series + attribution loop is the next layer.

Deeper design history lives in `CLAUDE.md` and the agent memory directory.
