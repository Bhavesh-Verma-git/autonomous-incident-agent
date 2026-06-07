"""
api/app.py — FastAPI application factory.

Follows the "application factory" pattern:
  - create_app() builds and returns the configured FastAPI instance
  - Never import the app object directly from this module in route files
    (that creates circular imports)
  - main.py imports create_app() and runs it with uvicorn

Middleware, CORS, exception handlers, and routers are all wired here.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import incidents_router, health_router, stream_router
from api.auth import verify_api_key

logging.basicConfig(
    level  = logging.INFO,
    format = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt= "%Y-%m-%dT%H:%M:%S",
)

log = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Modern lifespan handler (replaces deprecated @app.on_event)."""
    log.info("═" * 60)
    log.info("  AIRP API starting up")
    log.info("  Docs available at http://localhost:8000/docs")
    log.info("═" * 60)
    yield
    log.info("AIRP API shutting down — goodbye!")


def create_app() -> FastAPI:
    """
    Application factory — builds the configured FastAPI instance.

    Keeps app creation separate from module-level globals so you can
    call create_app() in tests with different configs.
    """
    app = FastAPI(
        title       = "Autonomous Incident Response Agent",
        description = (
            "AI-powered incident investigation system built on LangGraph. "
            "Accepts alert webhooks, runs parallel analysis, and produces "
            "structured root-cause reports. Supports Human-In-The-Loop "
            "escalation for low-confidence findings."
        ),
        version     = "1.0.0",
        docs_url    = "/docs",
        redoc_url   = "/redoc",
        lifespan    = _lifespan,
    )

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Allow the React dashboard (running on :5173 in dev) to call the API.
    # Tighten allow_origins in production.
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = ["*"],   # lock down in prod: ["http://localhost:5173"]
        allow_credentials = True,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception):
        log.exception(f"Unhandled error on {request.method} {request.url}: {exc}")
        return JSONResponse(
            status_code = 500,
            content     = {"error": "Internal server error"},
        )


    # ── Register routers ──────────────────────────────────────────────────────
    app.include_router(health_router)
    app.include_router(incidents_router, dependencies=[Depends(verify_api_key)])
    app.include_router(stream_router)

    # ── Serve dashboard static files ──────────────────────────────────────────
    import os
    from fastapi.staticfiles import StaticFiles
    dashboard_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard")
    if os.path.isdir(dashboard_dir):
        app.mount("/dashboard", StaticFiles(directory=dashboard_dir, html=True), name="dashboard")

    return app
