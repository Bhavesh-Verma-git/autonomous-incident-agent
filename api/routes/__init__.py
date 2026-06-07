"""
api/routes/__init__.py — Aggregates all route modules.

Add new router imports here and they automatically appear in the app.
"""

from api.routes.incidents import router as incidents_router
from api.routes.health    import router as health_router
from api.routes.stream    import router as stream_router

__all__ = ["incidents_router", "health_router", "stream_router"]

