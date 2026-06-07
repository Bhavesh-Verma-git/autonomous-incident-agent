"""
api/routes/health.py — Health check endpoints.

Used by:
  - Docker/Kubernetes liveness probes
  - Uptime monitoring tools
  - CI/CD pipelines to verify the service is up before running tests
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["Health"])

# Service start time (module-level so it's set once on import)
_START_TIME = time.time()


class HealthResponse(BaseModel):
    status:    str
    uptime_s:  float
    timestamp: datetime


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness check — is the service running?",
)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status    = "ok",
        uptime_s  = round(time.time() - _START_TIME, 2),
        timestamp = datetime.now(timezone.utc),
    )


@router.get(
    "/",
    summary="Root endpoint — returns API info",
)
async def root():
    return {
        "name":    "Autonomous Incident Response Agent API",
        "version": "1.0.0",
        "docs":    "/docs",
        "health":  "/health",
    }
