"""The engagement seam: act on others' content (signals now; replies/quotes later).

The outbound *action* counterpart to `publish/` — where the publisher broadcasts original drafts,
the engager reacts to a target (someone else's post/author). Targets come from swappable
`TargetSource`s (topical search now; reciprocal / curated / the reverse-poller later); actions go
through a capability-declaring `Engager` behind a live gate. Kept deliberately separate from the
reverse-poller: the two meet only through the `Target` type.
"""
