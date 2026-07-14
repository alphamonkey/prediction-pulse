# persona-pulse

A platform for running a **fleet of self-contained social media personas**. Each persona declares
its own stack — content source(s) → deterministic detection → LLM-written drafts in its voice →
publishing → engagement → measurement — and owns its own database, secrets, and process. One
systemd template unit runs any number of them side by side.

The first resident persona posts **prediction-market moves**: a deterministic pipeline detects
interesting events (odds swings, volume spikes, round-number milestones, notable new markets) from
free Kalshi data, selected by what's **trending on Bluesky**; Claude writes a punchy, accurate post
in the persona's voice; it publishes to Bluesky behind a pluggable interface (X / Threads /
Mastodon drop in later).

The point isn't generating text — anyone can do that. It's owning a **data → insight →
distribution** pipeline where the data is genuinely shareable, and measuring what travels before
spending on scale.

> **Status: live on Bluesky.** Dry-run by default — a persona only posts when its own secrets file
> sets `PULSE_MODE=live`, so new personas rehearse safely while others run live.

## A persona is a container

`personas/<name>/` holds the voice (`system_prompt.md`) and a `persona.toml` that declares
identity, channels, and the pipeline — **a job runs iff its section is present**, every field
falls back to `config.py` defaults:

```toml
display_name = "The Avaricious Gnome 🧙‍♂️"

# One block per account. Publish, engage and metrics all loop these — so adding a channel here
# (plus its secret in secrets/<persona>.env) is the whole change. No code.
[[channels]]
platform = "bluesky"
handle = "avariciousgnome.bsky.social"

# [[channels]]
# platform = "mastodon"                  # also Pleroma / Akkoma / GoToSocial
# instance = "https://mastodon.social"   # required — the adapter is instance-agnostic

[pipeline.poll]
sources = ["trend"]      # source registry: "kalshi" (category allowlist) | "trend" (Bluesky-trending)
interval = 900

[pipeline.draft]
interval = 3600

[pipeline.publish]
interval = 14400
jitter = 600
windows = [["07:00", "10:00"], ["12:00", "14:00"], ["17:00", "22:00"]]  # dayparted
tz = "America/New_York"

[pipeline.engage]        # like/repost relevant conversations, capped + dayparted
interval = 3600
windows = "publish"
queries = ["kalshi", "prediction market", "polymarket"]
actions = ["like", "repost"]

[pipeline.metrics]       # pull engagement back for the dashboard
interval = 3600
```

Alongside it: `secrets/<name>.env` (gitignored — creds + that persona's `PULSE_MODE`) and
`data/<name>.db` (gitignored — the persona's whole history). Delete those two files and the
persona never existed.

`pulse supervise <name>` runs everything the persona declares in one process — each job on its own
scheduler thread (publish/engage only inside their local-time windows), each with its own SQLite
connection, plus a daily retention prune. See `personas/example/` for a fully documented template.

## Pipeline

Every stage is a swappable seam (a `Protocol`) — new sources, writers, publishers, or platforms
drop in without touching the rest:

```
poll (source registry) ──▶ detector ──▶ writer ──▶ publisher ──▶ platform
 kalshi | trend | (yours)   (pure rules) (Claude/    (Bluesky,      ▲
        │                       │        template)    dry-run gate) │
        └───────▶ data/<persona>.db (SQLite+WAL) ◀────┴── metrics ──┘
                            │                          engage ──────┘
                  fleet dashboard (read-only, per-persona picker)
```

- **`venue/`** — `SnapshotSource` seam + registry. `KalshiSource` (category allowlist) and
  `BlueskyTrendSource` (markets matched to Bluesky trending topics). A new content source is one
  registry entry.
- **`detector/`** — pure, deterministic rules over normalized snapshots. No LLM. TDD.
- **`writer/` + `persona.py`** — event → post in the persona's voice. `ClaudeWriter` (Haiku,
  cheap) when a key is set, else a zero-cost `TemplateWriter`.
- **`publish/`** — `Publisher` seam; `BlueskyPublisher` live, `DryRunPublisher` otherwise.
  Idempotent, rate-capped, freshest-first.
- **`engage/`** — outbound signals (like/repost/follow) on relevant conversations: search →
  relevance/safety filter → capped, idempotent actions behind the same live gate.
- **`metrics/`** — `EngagementSource` seam; pulls engagement back per persona. Capability-driven
  over a normalized `MetricKind` vocabulary so platforms with different metric sets slot in.
- **`scheduler/`** — `Job`/`Scheduler` seam; interval + dayparted (windowed) schedulers.
- **`supervisor.py`** — assembles a persona's declared jobs and runs them as one process.
- **`server/`** — read-only FastAPI dashboard for the whole fleet: persona picker, KPM scorecard
  (followers + growth, applause/conversation/amplification, top posts), pipeline throughput.

## CLI

```
pulse supervise <name> ................ run EVERYTHING the persona declares (the service body)
pulse poll|run   [--source --persona]   one-shot / cadenced poll+detect
pulse draft      [--persona --limit]    write drafts for top recent events
pulse publish    [--persona --limit]    post the persona's freshest drafts
pulse engage     [--persona --limit]    like/repost relevant conversations
pulse metrics    [--persona --limit]    collect engagement back
pulse prune      [--persona]            retention cleanup (also runs daily inside supervise)
pulse vacuum     [--persona]            one-time DB compaction (stop the persona's supervisor first)
pulse serve      [--host --port]        the fleet dashboard
```

Everything is dry-run until the persona's env sets `PULSE_MODE=live`.

## Deploy (systemd, `deploy/`)

One template runs the fleet:

```bash
sudo cp deploy/pulse@.service /etc/systemd/system/ && sudo systemctl daemon-reload
sudo systemctl enable --now pulse@gnome        # one instance per persona
journalctl -u pulse@gnome -f                   # that persona's logs
```

Adding a persona = `personas/<name>/` + `secrets/<name>.env` (copy `deploy/persona.env.example`)
+ `systemctl enable --now pulse@<name>`. The dashboard runs as its own unit
(`persona-pulse-dashboard.service`, `:8440`).

**Unit-file gotcha:** changing `deploy/*.service` requires re-copying to `/etc/systemd/system/` +
`daemon-reload` + restart — `git pull` alone doesn't apply unit changes (code changes do apply on
a plain restart).

## Setup

```bash
virtualenv .venv && .venv/bin/pip install -e '.[dev,server]'
mkdir -p secrets && cp deploy/persona.env.example secrets/example.env   # fill in; PULSE_MODE=dryrun
.venv/bin/pytest
.venv/bin/pulse supervise example --max-iterations 1   # one dry cycle of every declared job
```

Global defaults (cadences, caps, detector thresholds, `RULE_WEIGHTS`) live in
`src/pulse/config.py`; anything a persona sets in its `[pipeline]` overrides them. Credentials
never leave `secrets/` (gitignored).

## Conventions

- **Real data only — never fabricate numbers.** Light "not financial advice" framing; no
  agriculture/food topics.
- **Dry-run first** — review a new persona's copy before flipping its `PULSE_MODE=live`.
- **TDD**, deterministic core, LLM only for the judgment/language task. Reach `main` via PR.

## Next / open

- Surface API cost on the dashboard (issue #6); attach the market link per platform (issue #7);
  persona hot-reload (issue #13 — the supervisor is its natural home).
- New content-source types beyond prediction markets (the registry is the extension point) and a
  persona scaffolding command.
- Reply/quote engagement (LLM-written), reciprocal/curated-list target sources, tuning dayparting
  windows from real activity data.
- **Engagement pull-back, deeper:** per-post engagement *over time* + rule→engagement attribution
  (which detector rule travels best → tune `RULE_WEIGHTS`).
- Cross-posting (X / Threads) behind the existing channel seam.

Deeper design history lives in `CLAUDE.md`, `docs/superpowers/specs/`, and the agent memory
directory.
