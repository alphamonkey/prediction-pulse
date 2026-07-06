"""Read-only monitoring dashboard.

A FastAPI app serving a single static page (Tailwind + Chart.js via CDN, no build step) plus JSON
endpoints. Each request opens its own READ-ONLY SQLite connection, so the dashboard is safe to run
alongside the writer/poller. Mirrors kalshi-edge's server.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from pulse import config
from pulse.store.db import Database
from pulse.venue.trending import BlueskyTrendClient

STATIC = Path(__file__).parent / "static"


def create_app(trend_client: BlueskyTrendClient | None = None) -> FastAPI:
    # Ensure the DB file + schema exist once (read-only open fails on a missing/old schema);
    # this also creates the `drafts` table on a DB whose service predates it.
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

    @app.get("/api/stats")
    def stats() -> JSONResponse:
        db = Database.connect_readonly(config.db_path())
        try:
            payload = db.stats()
            payload["mode"] = config.pulse_mode()
            return JSONResponse(payload)
        finally:
            db.close()

    @app.get("/api/events")
    def events(limit: int = 20) -> JSONResponse:
        db = Database.connect_readonly(config.db_path())
        try:
            return JSONResponse(db.get_recent_events(limit))
        finally:
            db.close()

    @app.get("/api/drafts")
    def drafts(limit: int = 20) -> JSONResponse:
        db = Database.connect_readonly(config.db_path())
        try:
            return JSONResponse(db.get_drafts(limit))
        finally:
            db.close()

    @app.get("/api/kpms")
    def kpms() -> JSONResponse:
        db = Database.connect_readonly(config.db_path())
        try:
            return JSONResponse(db.kpms())
        finally:
            db.close()

    @app.get("/api/followers")
    def followers(days: int = 30) -> JSONResponse:
        db = Database.connect_readonly(config.db_path())
        try:
            return JSONResponse(db.follower_series(days))
        finally:
            db.close()

    @app.get("/api/top-posts")
    def top_posts(limit: int = 5) -> JSONResponse:
        db = Database.connect_readonly(config.db_path())
        try:
            return JSONResponse(db.top_posts(limit))
        finally:
            db.close()

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
