"""
api/dependencies.py — FastAPI dependency injection.

All shared singletons (graph, in-memory store) live here.
Use FastAPI's Depends() to inject them into route handlers.
This keeps route handlers thin and testable.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from graph.graph import get_graph
from api.store import IncidentStore


# ── Graph Singleton ───────────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _build_graph():
    """
    Build the LangGraph compiled graph exactly ONCE per process lifetime.
    lru_cache ensures the SqliteSaver connection is reused, not re-opened.
    """
    return get_graph()


def get_agent_graph():
    """FastAPI dependency: injects the compiled LangGraph into route handlers."""
    return _build_graph()


# ── Incident Store Singleton ──────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _build_store():
    """Single IncidentStore instance shared across all requests."""
    return IncidentStore()


def get_incident_store():
    """FastAPI dependency: injects the IncidentStore into route handlers."""
    return _build_store()


# ── Type aliases (cleaner route signatures) ───────────────────────────────────

GraphDep = Annotated[object,        Depends(get_agent_graph)]
StoreDep  = Annotated[IncidentStore, Depends(get_incident_store)]
