# One-time cutover: per-stage services → `pulse@gnome` supervisor

The persona-as-container refactor replaces six per-stage units with one supervisor instance per
persona. This runbook migrates the live gnome deployment. **Total downtime: minutes.** Every step
is reversible until the final cleanup.

Run from the repo root on the box, after merging all refactor PRs and `git pull` on main.
(`sudo` steps are marked; the operator runs them.)

## 0. Preconditions

- [ ] `git log --oneline -1` shows the dashboard-picker PR (or later) merged
- [ ] `.venv/bin/pytest` green
- [ ] `.venv/bin/pip install -e '.[dev,server]'` re-run (new console entrypoints not needed, but be safe)
- [ ] **Do not restart any old per-stage service from here on** (new code + old units would
      split writes onto `data/gnome.db` prematurely)

## 1. Per-persona secrets

```bash
mkdir -p secrets
cp deploy/persona.env.example secrets/gnome.env
# then fill secrets/gnome.env from the current .env values:
#   PULSE_MODE=live  BLUESKY_HANDLE=...  BLUESKY_APP_PASSWORD=...  ANTHROPIC_API_KEY=...
chmod 600 secrets/gnome.env
```

## 2. Stop the old stack (leave the dashboard running)

```bash
sudo systemctl stop prediction-pulse-trendpoller prediction-pulse-drafter \
  prediction-pulse-publisher prediction-pulse-engager prediction-pulse-metrics
sudo systemctl stop prediction-pulse-prune.timer
```

## 3. Move the DB into the persona layout

```bash
mkdir -p data
sqlite3 prediction_pulse.db 'PRAGMA wal_checkpoint(TRUNCATE);'
mv prediction_pulse.db data/gnome.db
```

## 4. Install + start the supervisor

```bash
sudo cp deploy/pulse@.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pulse@gnome
```

## 5. Verify

- [ ] `journalctl -u pulse@gnome -f` — supervisor line lists `poll:trend, draft, publish, engage,
      metrics, prune`, `mode=live`, no tracebacks over a few minutes
- [ ] dashboard (`:8440`) shows gnome via the persona picker; KPMs populated (it reads
      `data/gnome.db` now)
- [ ] after the next window: posts/engagement continue as before

**Rollback** (any time before step 6): `sudo systemctl disable --now pulse@gnome`, move
`data/gnome.db` back to `prediction_pulse.db`, `sudo systemctl start` the old services.

## 6. Retire the old units (point of no return-ish — they're still in git)

```bash
sudo systemctl disable prediction-pulse-trendpoller prediction-pulse-drafter \
  prediction-pulse-publisher prediction-pulse-engager prediction-pulse-metrics \
  prediction-pulse prediction-pulse-prune.timer prediction-pulse-prune
sudo rm /etc/systemd/system/prediction-pulse-{trendpoller,drafter,publisher,engager,metrics,prune}.service \
       /etc/systemd/system/prediction-pulse-prune.timer /etc/systemd/system/prediction-pulse.service
sudo systemctl daemon-reload
```

The dashboard unit (`prediction-pulse-dashboard.service`) stays as-is.
