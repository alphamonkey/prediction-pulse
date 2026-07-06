"""The relevance/safety filter — pure functions over Targets.

A target is engaged only if its author is *not excluded* (self is never a valid target — the engage
layer feeds our own handle in; the same mechanism serves any future blocklist) AND it is *relevant*
(matches the topic allowlist, when one is set) AND *safe* (contains none of the denylisted terms — the
persona no-go topics: politics/lightning-rod, agriculture/food). Topic matching is case-insensitive
substring; the denylist deliberately over-rejects. Author exclusion is an exact (case-insensitive)
handle match.
"""

from __future__ import annotations

from collections.abc import Iterable

from pulse.engage.base import Target


def passes_filter(
    target: Target, *, allow: Iterable[str], deny: Iterable[str],
    exclude_handles: Iterable[str] = (),
) -> bool:
    # Author gate first: an excluded author (self, for now and always) is never a valid target,
    # no matter how relevant/safe the text is.
    if target.author_handle.lower() in {h.lower() for h in exclude_handles if h}:
        return False
    text = target.text.lower()
    if any(term.lower() in text for term in deny):
        return False
    allow = list(allow)
    if allow and not any(term.lower() in text for term in allow):
        return False
    return True


def filter_targets(
    targets: Iterable[Target], *, allow: Iterable[str], deny: Iterable[str],
    exclude_handles: Iterable[str] = (),
) -> list[Target]:
    """Keep valid (non-excluded, relevant, safe) targets, de-duplicated by uri (first wins)."""
    allow, deny = list(allow), list(deny)
    excluded = {h.lower() for h in exclude_handles if h}
    seen: set[str] = set()
    out: list[Target] = []
    for t in targets:
        if t.uri in seen:
            continue
        if passes_filter(t, allow=allow, deny=deny, exclude_handles=excluded):
            seen.add(t.uri)
            out.append(t)
    return out
