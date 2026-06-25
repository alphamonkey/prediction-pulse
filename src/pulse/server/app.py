"""Read-only monitoring dashboard.

A FastAPI app serving a single static page (Tailwind + Chart.js via CDN, no build step) plus JSON
endpoints. Each request opens its own READ-ONLY SQLite connection, so the dashboard is safe to run
alongside the writer/poller. Mirrors kalshi-edge's server.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse

from pulse import config
from pulse.store.db import Database

STATIC = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    # Ensure the DB file + schema exist once (read-only open fails on a missing/old schema);
    # this also creates the `drafts` table on a DB whose service predates it.
    boot = Database(config.DB_PATH)
    boot.connect()
    boot.close()

    app = FastAPI(title="prediction-pulse", docs_url="/api/docs")

    @app.get("/api/stats")
    def stats() -> JSONResponse:
        db = Database.connect_readonly(config.DB_PATH)
        try:
            payload = db.stats()
            payload["mode"] = config.PULSE_MODE
            return JSONResponse(payload)
        finally:
            db.close()

    @app.get("/api/events")
    def events(limit: int = 20) -> JSONResponse:
        db = Database.connect_readonly(config.DB_PATH)
        try:
            return JSONResponse(db.get_recent_events(limit))
        finally:
            db.close()

    @app.get("/api/drafts")
    def drafts(limit: int = 20) -> JSONResponse:
        db = Database.connect_readonly(config.DB_PATH)
        try:
            return JSONResponse(db.get_drafts(limit))
        finally:
            db.close()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


def serve(host: str = config.DASHBOARD_HOST, port: int = config.DASHBOARD_PORT) -> None:
    import uvicorn

    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
