# Generator content source — generalize the poll seam

**Date:** 2026-07-09 · **Status:** approved

## Problem

The persona-as-container refactor made the middle of the stack (draft → publish → engage →
metrics) generic, but the edges are market-shaped. A persona with *no external input* (first
target: "Bean Facts", which invents silly false bean facts) cannot exist without platform code:

1. `poll_once` hard-codes `SnapshotSource.fetch_snapshots → insert_snapshot → run_detection`.
2. Registry builders are `Callable[[KalshiClient], SnapshotSource]`; `supervise()` constructs a
   `KalshiClient` whenever `[pipeline.poll]` exists — generator personas shouldn't need Kalshi
   creds.
3. Sources are config-less names; a generator needs per-source config.
4. `Event` carries market residue: required `value_kind`, an unconditional "Market:" line in
   `_render_event`.

Desired end state: creating a no-external-input persona is pure config
(`personas/<name>/persona.toml` + `system_prompt.md` + `secrets/<name>.env`).

## Design

### ContentSource seam

Sources emit `Event`s; market snapshot polling becomes one implementation.

```python
class ContentSource(Protocol):
    venue: str
    def fetch_events(self, db: Database, now: datetime) -> list[Event]: ...
```

`SnapshotContentSource` adapts any existing `SnapshotSource` (fetch → store → detect), so
`kalshi`/`trend` behave identically. `poll_once` depends only on `ContentSource` and records the
returned events; `PollReport.events` still means *newly recorded* events, with
`db.record_posted`'s `INSERT OR IGNORE` as the race-safe backstop.

### Per-source config

`[[pipeline.poll.source]]` tables — `type = "..."` plus source-owned keys, parsed into
`SourceSpec(type, options)`. `sources = ["trend"]` remains supported as sugar for
`[{type = "trend"}]` (gnome's file is unchanged); declaring both forms is an error. Pipeline
parsing stays strict on its own keys; **option**-key validation is owned by each source builder,
which raises on unknown keys naming the source type.

### Registry + lazy SourceContext

`make_source(spec: SourceSpec, ctx: SourceContext) -> ContentSource`. `SourceContext` exposes a
lazy, memoized `kalshi()` factory; only builders that call it construct a client, and
`supervise()` closes it only if materialized. Builders: `kalshi`, `trend` (adapter-wrapped),
`generator`.

### GeneratorSource (no external input)

Emits seed `Event`s; **the generator never calls the LLM** — invention happens in the writer,
where cost tracking/caching and the `TemplateWriter` dryrun fallback already live. The persona's
`system_prompt.md` carries the voice and the "invent" instruction.

Options: `topics` (seed list; default one generic seed), `count` (events per cycle, default 1),
`bucket` (dedup time-granularity, e.g. `"4h"`; default = poll interval). Emitted shape:
`rule="generated"`, `venue="generator"`, `market_id=<topic-slug>`, `headline=<seed>`,
`dedup_key="generated:<topic-slug>:<bucket-ts>"`, `magnitude=1.0`, numerics `None`,
`context={"source_kind": "generated"}`. Topic rotation is deterministic per bucket, so re-polls
and restarts are idempotent.

### Event softening (no migration)

`Event.value_kind: ValueKind | None` (type widened in place; `market_id` documented as a generic
subject id — no column renames). The DB round-trip discriminator is
`context["source_kind"] == "generated"` (context is persisted JSON); `_row_to_event` sets
`value_kind=None` for those rows. `_render_event` skips the "Market:" line for generated events.
`RULE_WEIGHTS` gains `"generated": 1.0`.

## Out of scope

The Bean Facts persona itself (next session); `rule` label override; news/weather sources (the
seam now admits them); persona scaffolding tooling.
