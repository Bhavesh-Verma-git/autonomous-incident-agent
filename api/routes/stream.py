"""
api/routes/stream.py — Server-Sent Events (SSE) streaming endpoint.

GET /incidents/{incident_id}/stream

Clients connect once and receive a continuous text/event-stream of node
completion events as the LangGraph executes. The connection closes
automatically when the graph finishes or the client disconnects.

SSE format (RFC):
    data: {"event": "node_complete", "node": "log_analysis_node", ...}\n\n

Why SSE over WebSockets?
- SSE is unidirectional (server→client) — perfect for watching graph progress
- Works over plain HTTP/1.1, no upgrade needed
- Auto-reconnects built into the browser EventSource API
- WebSockets are needed only for bidirectional communication (the HITL resume
  uses a regular POST endpoint, which is simpler and more reliable)
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue as queue_module
from typing import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from api.dependencies import StoreDep
from api.schemas import IncidentStatusEnum

log    = logging.getLogger(__name__)
router = APIRouter(tags=["Streaming"])


async def _event_generator(
    record,
    q: queue_module.Queue,
) -> AsyncGenerator[str, None]:
    """
    Async generator that yields SSE-formatted strings.

    Reads events from the thread-safe queue (populated by runner.py)
    and yields them in SSE format. Uses asyncio.sleep(0) to yield
    control back to the event loop between queue polls so FastAPI
    can handle other requests concurrently.
    """
    try:
        # If the incident is already done, send a synthetic summary and close
        if record.status in (IncidentStatusEnum.COMPLETED, IncidentStatusEnum.FAILED):
            yield _fmt({"event": "status", "data": record.status.value})
            return

        while True:
            # Non-blocking queue get with a tiny sleep to avoid busy-wait
            try:
                event = q.get_nowait()
            except queue_module.Empty:
                # No events yet — yield control, then retry
                await asyncio.sleep(0.1)
                continue

            if event is None:
                # Sentinel: stream is done (graph completed or failed)
                yield _fmt({"event": "done", "data": "stream_closed"})
                break

            yield _fmt(event)

            # Auto-close when a terminal status is received
            if event.get("event") == "status" and event.get("data") in (
                "completed", "failed"
            ):
                break

    except asyncio.CancelledError:
        # Client disconnected
        log.info(f"[stream] Client disconnected from {record.incident_id}")
    finally:
        record.unsubscribe(q)


def _fmt(event: dict) -> str:
    """Format a dict as a valid SSE message."""
    return f"data: {json.dumps(event)}\n\n"


@router.get(
    "/incidents/{incident_id}/stream",
    summary="Stream real-time graph progress via SSE",
    description=(
        "Connect with EventSource in the browser to receive per-node progress "
        "events as the LangGraph executes. The stream closes automatically when "
        "the graph finishes. Reconnect after HITL resume to see remaining nodes."
    ),
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}},
        404: {"description": "Incident not found"},
    },
)
async def stream_incident(
    incident_id: str,
    store:       StoreDep,
) -> StreamingResponse:

    record = store.get(incident_id)
    if record is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    # Subscribe to the event bus — each client gets its own queue
    q = record.subscribe()

    return StreamingResponse(
        _event_generator(record, q),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",    # disable nginx buffering
            "Access-Control-Allow-Origin": "*",
        },
    )
