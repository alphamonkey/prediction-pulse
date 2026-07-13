"""PipelineSpec — the stack a persona declares in persona.toml's [pipeline.*] sections.

A job runs iff its section is present; omitted fields fall back to config defaults. This makes
persona.toml the policy layer and config.py the defaults layer. Parsing is pure (dict in,
frozen dataclasses out) and strict: unknown sections/keys raise ValueError so operator typos
fail loudly at load time instead of silently running defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pulse import config

Windows = tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SourceSpec:
    """One declared content source: its registry type + source-owned options.

    The pipeline parser passes `options` through verbatim — each source builder owns the
    validation of its own keys (the strictness lives with the seam that defines the keys).
    """

    type: str
    options: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PollSpec:
    sources: tuple[SourceSpec, ...] = (SourceSpec("kalshi"),)
    interval: int = config.DEFAULT_INTERVAL_SECONDS
    jitter: int = 0


@dataclass(frozen=True)
class DraftSpec:
    interval: int = config.DRAFT_INTERVAL_SECONDS
    limit: int = config.DRAFTS_PER_RUN
    jitter: int = 0


@dataclass(frozen=True)
class PublishSpec:
    interval: int = config.PUBLISH_INTERVAL_SECONDS
    jitter: int = 0
    windows: Windows = config.PUBLISH_WINDOWS
    tz: str = config.ACTIVE_TZ
    limit: int = config.POSTS_PER_CYCLE  # per CYCLE; the daily cap is config.MAX_POSTS_PER_DAY


@dataclass(frozen=True)
class EngageSpec:
    interval: int = config.ENGAGE_INTERVAL_SECONDS
    jitter: int = 0
    windows: Windows = config.ENGAGE_WINDOWS
    tz: str = config.ACTIVE_TZ
    queries: tuple[str, ...] = config.ENGAGE_QUERIES
    allow: tuple[str, ...] = config.ENGAGE_ALLOW
    deny: tuple[str, ...] = config.ENGAGE_DENY
    actions: tuple[str, ...] = config.ENGAGE_ACTIONS
    caps: dict = field(default_factory=dict)
    limit: int = config.ENGAGE_TARGETS_PER_RUN


@dataclass(frozen=True)
class MetricsSpec:
    interval: int = config.METRICS_INTERVAL_SECONDS
    post_limit: int = config.METRICS_POST_WINDOW
    jitter: int = 0


@dataclass(frozen=True)
class PipelineSpec:
    poll: PollSpec | None = None
    draft: DraftSpec | None = None
    publish: PublishSpec | None = None
    engage: EngageSpec | None = None
    metrics: MetricsSpec | None = None


_SECTIONS = ("poll", "draft", "publish", "engage", "metrics")

_DEFAULT_CAPS = {
    "like": config.MAX_LIKES_PER_DAY,
    "repost": config.MAX_REPOSTS_PER_DAY,
    "follow": config.MAX_FOLLOWS_PER_DAY,
}


def _check_keys(section: str, data: dict, allowed: tuple[str, ...]) -> None:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValueError(
            f"[pipeline.{section}] has unknown key(s): {', '.join(sorted(unknown))}")


def _parse_windows(section: str, raw) -> Windows:
    pairs = []
    for pair in raw:
        if len(pair) != 2:
            raise ValueError(
                f"[pipeline.{section}] windows entries must be [\"HH:MM\", \"HH:MM\"] pairs")
        pairs.append((str(pair[0]), str(pair[1])))
    return tuple(pairs)


def _parse_sources(data: dict) -> tuple[SourceSpec, ...]:
    """`sources = ["trend"]` is sugar for `[[pipeline.poll.source]]` tables with only a type."""
    if "sources" in data and "source" in data:
        raise ValueError("[pipeline.poll] declares both `sources` and `source` — use one form")
    if "sources" in data:
        return tuple(SourceSpec(str(name)) for name in data["sources"])
    if "source" in data:
        specs = []
        for entry in data["source"]:
            if "type" not in entry:
                raise ValueError("[[pipeline.poll.source]] entries must declare a `type`")
            options = {k: v for k, v in entry.items() if k != "type"}
            specs.append(SourceSpec(str(entry["type"]), options))
        return tuple(specs)
    return PollSpec.sources


def parse_pipeline(table: dict) -> PipelineSpec:
    """Parse the (possibly absent) `[pipeline]` table of a persona.toml."""
    unknown = set(table) - set(_SECTIONS)
    if unknown:
        raise ValueError(f"[pipeline] has unknown section(s): {', '.join(sorted(unknown))}")

    poll = draft = publish = engage = metrics = None

    if "poll" in table:
        data = table["poll"]
        _check_keys("poll", data, ("sources", "source", "interval", "jitter"))
        poll = PollSpec(
            sources=_parse_sources(data),
            interval=data.get("interval", PollSpec.interval),
            jitter=data.get("jitter", PollSpec.jitter),
        )

    if "draft" in table:
        data = table["draft"]
        _check_keys("draft", data, ("interval", "limit", "jitter"))
        draft = DraftSpec(
            interval=data.get("interval", DraftSpec.interval),
            limit=data.get("limit", DraftSpec.limit),
            jitter=data.get("jitter", DraftSpec.jitter),
        )

    if "publish" in table:
        data = table["publish"]
        _check_keys("publish", data, ("interval", "jitter", "windows", "tz", "limit"))
        publish = PublishSpec(
            interval=data.get("interval", PublishSpec.interval),
            jitter=data.get("jitter", PublishSpec.jitter),
            windows=(_parse_windows("publish", data["windows"])
                     if "windows" in data else PublishSpec.windows),
            tz=data.get("tz", PublishSpec.tz),
            limit=data.get("limit", PublishSpec.limit),
        )

    if "engage" in table:
        data = table["engage"]
        _check_keys("engage", data, ("interval", "jitter", "windows", "tz", "queries",
                                     "allow", "deny", "actions", "caps", "limit"))
        if data.get("windows") == "publish":
            # Alias: mirror this persona's publish windows (declared or default).
            windows = publish.windows if publish is not None else PublishSpec.windows
        elif "windows" in data:
            windows = _parse_windows("engage", data["windows"])
        else:
            windows = EngageSpec.windows
        queries = tuple(data["queries"]) if "queries" in data else EngageSpec.queries
        # The relevance allowlist defaults to the persona's own search queries (same
        # relationship as the global ENGAGE_ALLOW = ENGAGE_QUERIES).
        allow = tuple(data["allow"]) if "allow" in data else queries
        engage = EngageSpec(
            interval=data.get("interval", EngageSpec.interval),
            jitter=data.get("jitter", EngageSpec.jitter),
            windows=windows,
            tz=data.get("tz", EngageSpec.tz),
            queries=queries,
            allow=allow,
            deny=tuple(data["deny"]) if "deny" in data else EngageSpec.deny,
            actions=tuple(data["actions"]) if "actions" in data else EngageSpec.actions,
            caps={**_DEFAULT_CAPS, **data.get("caps", {})},
            limit=data.get("limit", EngageSpec.limit),
        )

    if "metrics" in table:
        data = table["metrics"]
        _check_keys("metrics", data, ("interval", "post_limit", "jitter"))
        metrics = MetricsSpec(
            interval=data.get("interval", MetricsSpec.interval),
            post_limit=data.get("post_limit", MetricsSpec.post_limit),
            jitter=data.get("jitter", MetricsSpec.jitter),
        )

    return PipelineSpec(poll=poll, draft=draft, publish=publish, engage=engage, metrics=metrics)
