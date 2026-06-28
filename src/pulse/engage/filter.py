"""The relevance/safety filter — pure functions over Targets.

A target is engaged only if it is *relevant* (matches the topic allowlist, when one is set) AND
*safe* (contains none of the denylisted terms — the persona no-go topics: politics/lightning-rod,
agriculture/food). Matching is case-insensitive substring; the denylist deliberately over-rejects.
"""

from __future__ import annotations

from collections.abc import Iterable

from pulse.engage.base import Target


def passes_filter(target: Target, *, allow: Iterable[str], deny: Iterable[str]) -> bool:
    text = target.text.lower()
    if any(term.lower() in text for term in deny):
        return False
    allow = list(allow)
    if allow and not any(term.lower() in text for term in allow):
        return False
    return True


def filter_targets(
    targets: Iterable[Target], *, allow: Iterable[str], deny: Iterable[str]
) -> list[Target]:
    """Keep relevant + safe targets, de-duplicated by uri (first occurrence wins)."""
    allow, deny = list(allow), list(deny)
    seen: set[str] = set()
    out: list[Target] = []
    for t in targets:
        if t.uri in seen:
            continue
        if passes_filter(t, allow=allow, deny=deny):
            seen.add(t.uri)
            out.append(t)
    return out
