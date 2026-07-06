"""Read-only monitoring dashboard — one service for the whole persona fleet.

A FastAPI app serving a single static page (Tailwind + Chart.js via CDN, no build step) plus JSON
endpoints. Personas are discovered from the data dir (data/*.db) per request, so a newly started
persona appears without a restart; every data route takes ?persona= and opens that persona's DB
READ-ONLY, so the dashboard is safe to run alongside all the supervisors.
"""

from __future__ import annotations

import contextlib
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from pulse import config
from pulse.store.db import Database
from pulse.venue.trending import BlueskyTrendClient

STATIC = Path(__file__).parent / "static"


def _personas() -> list[str]:
    """Persona names with a DB in the data dir. The filename IS the persona key."""
    return sorted(p.stem for p in Path(config.data_dir()).glob("*.db"))


def _resolve(persona: str | None) -> tuple[str | None, str]:
    """(persona, db-path) for a request. None → the first discovered persona, or the legacy
    single-DB layout when no per-persona DBs exist yet. Unknown names 404 — the name must come
    from discovery, never be treated as a path."""
    names = _personas()
    if persona is None:
        if not names:
            return None, config.db_path()  # pre-migration layout
        persona = names[0]
    if persona not in names:
        raise HTTPException(status_code=404, detail=f"unknown persona {persona!r}")
    return persona, str(Path(config.data_dir()) / f"{persona}.db")


@contextlib.contextmanager
def _db(persona: str | None):
    resolved, path = _resolve(persona)
    db = Database.connect_readonly(path)
    try:
        yield resolved, db
    finally:
        db.close()


def create_app(trend_client: BlueskyTrendClient | None = None) -> FastAPI:
    # Pre-migration convenience: with no per-persona DBs yet, ensure the legacy file + schema
    # exist once (read-only open fails on a missing/old schema). Per-persona DBs are created by
    # their own supervisors — never by the dashboard.
    if not _personas():
        boot = Database(config.db_path())
        boot.connect()
        boot.close()

    # Live Bluesky trends for the widget — ephemeral, not persisted (see memory
    # `dashboard-external-fetch-ok`). One lazy-login client shared across requests, with a
    # server-side TTL cache + lock (uvicorn runs sync endpoints in a threadpool).
    trends_client = trend_client or BlueskyTrendClient(
        config.bluesky_handle(), config.bluesky_app_password())
    trends_cache: dict = {"at": 0.0, "data": []}
    trends_lock = threading.Lock()

    app = FastAPI(title="prediction-pulse", docs_url="/api/docs")

    @app.get("/api/personas")
    def personas() -> JSONResponse:
        names = _personas()
        return JSONResponse({"personas": names, "default": names[0] if names else None})

    @app.get("/api/stats")
    def stats(persona: str | None = None) -> JSONResponse:
        with _db(persona) as (resolved, db):
            payload = db.stats()
            payload["mode"] = config.pulse_mode()
            payload["persona"] = resolved
            return JSONResponse(payload)

    @app.get("/api/events")
    def events(limit: int = 20, persona: str | None = None) -> JSONResponse:
        with _db(persona) as (_, db):
            return JSONResponse(db.get_recent_events(limit))

    @app.get("/api/drafts")
    def drafts(limit: int = 20, persona: str | None = None) -> JSONResponse:
        with _db(persona) as (_, db):
            return JSONResponse(db.get_drafts(limit))

    @app.get("/api/kpms")
    def kpms(persona: str | None = None) -> JSONResponse:
        with _db(persona) as (_, db):
            return JSONResponse(db.kpms())

    @app.get("/api/followers")
    def followers(days: int = 30, persona: str | None = None) -> JSONResponse:
        with _db(persona) as (_, db):
            return JSONResponse(db.follower_series(days))

    @app.get("/api/top-posts")
    def top_posts(limit: int = 5, persona: str | None = None) -> JSONResponse:
        with _db(persona) as (_, db):
            return JSONResponse(db.top_posts(limit))

    @app.get("/api/trends")
    def trends(limit: int = config.DASHBOARD_TRENDS_LIMIT) -> JSONResponse:
        with trends_lock:
            if time.monotonic() - trends_cache["at"] >= config.DASHBOARD_TRENDS_TTL_SECONDS:
                fetched = trends_client.get_trends(limit=config.DASHBOARD_TRENDS_LIMIT)
                # Generic shape so a second platform (X/Google) slots in with no UI change.
                trends_cache["data"] = [
                    {"name": t.display_name, "post_count": t.post_count,
                     "category": t.category, "platform": "bluesky"}
                    for t in fetched
                ]
                trends_cache["at"] = time.monotonic()  # cache empties too — bounds retry on outages
            return JSONResponse(trends_cache["data"][:limit])

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


def serve(host: str = config.DASHBOARD_HOST, port: int = config.DASHBOARD_PORT) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
