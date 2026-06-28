# HANDOFF — kickoff prompt for the next agent

Paste the block below to bring a fresh agent up to speed. (In a Claude Code session in this repo,
`CLAUDE.md` and the `MEMORY.md` index load automatically — but the prompt still tells the agent to
read the *linked* memory files, which is where the real depth lives.)

---

```
You're picking up prediction-pulse — a faceless, data-driven prediction-market content
bot that's BUILT and running LIVE on Bluesky. Before doing anything, get oriented:

1. Read CLAUDE.md (the as-built architecture map — it's the project brief).
2. Read README.md (pipeline, CLI, services).
3. Read the agent memory: open MEMORY.md in the memory directory and then actually read
   each linked file — especially:
     - architecture-decisions.md  (every design decision + chunk-by-chunk build phasing
       + current status)
     - working-rules.md           (process constraints: TDD, clean arch, PR-to-main, etc.)
     - deploy-ops.md              (code changes apply on `systemctl restart`; deploy/*.service
       changes must be re-copied to /etc/systemd/system/ — git pull alone won't apply them)
     - git-state-freshness.md     (verify remote/PR state with a live query, not stale refs)

Current state to confirm before you trust it:
- It's LIVE (PULSE_MODE=live). Four systemd services run: poller (15m), drafter (1h),
  publisher (4h+jitter), dashboard (:8440). Verify with `systemctl is-active` and check
  the dashboard / recent posts before assuming anything.
- Run `git fetch && gh pr list` first — there may be an open PR awaiting merge.
- `.venv/bin/pytest` should show 142 pass + 1 known red (test_defaults_to_dryrun, which
  fails only because .env sets PULSE_MODE=live — a test-isolation quirk, not a real bug).

How we work here: brainstorm → plan (plan mode) → TDD chunk-by-chunk → PR to main (never
local-merge; gh is authed as alphamonkey). Dry-run first, real data only (never fabricate
numbers), light "not financial advice" framing, no agriculture/food topics. Personas under
personas/ are the operator's content — don't edit their voice without asking. The operator
runs sudo via the `!` prefix (no passwordless sudo).

Likely next work (confirm with me before starting): snapshot retention/pruning — the
market_snapshots table grows unbounded and is the root cause behind past lock contention —
and a new detector type I'm designing. Smaller loose ends: a tiny test-isolation fix for
test_defaults_to_dryrun and a duplicated comment at scheduler/interval.py:27.

Start by reading the above and giving me a short summary of your understanding + what you
think the best next step is. Don't write code until we've agreed on a plan.
```
