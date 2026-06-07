"""
api/routes/incidents.py — All incident-related API endpoints.

Endpoints:
    POST   /incidents/trigger              → Start a new incident investigation
    GET    /incidents                      → List all incidents (status board)
    GET    /incidents/{incident_id}        → Get status of one incident
    GET    /incidents/{incident_id}/report → Get full report (once completed)
    POST   /incidents/{incident_id}/resume → Resume a HITL-paused incident
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, status

from agents.models import Alert, Severity
from agents.security import SecurityGuard, RelevanceGuard
from api.dependencies import GraphDep, StoreDep
from api.runner import start_incident, resume_incident
from api.schemas import (
    HITLResumeRequest,
    HITLResumeResponse,
    IncidentReportResponse,
    IncidentStatusEnum,
    IncidentSummary,
    RootCauseResponse,
    TriggerIncidentRequest,
    TriggerIncidentResponse,
)

log      = logging.getLogger(__name__)
router   = APIRouter(prefix="/incidents", tags=["Incidents"])


# ── POST /incidents/trigger ───────────────────────────────────────────────────

@router.post(
    "/trigger",
    response_model=TriggerIncidentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a new incident investigation",
    description=(
        "Accepts an alert payload from PagerDuty, Datadog, or any webhook-compatible "
        "alerting tool. Immediately returns 202 Accepted and processes the graph "
        "asynchronously in a background thread."
    ),
)
async def trigger_incident(
    body:  TriggerIncidentRequest,
    graph: GraphDep,
    store: StoreDep,
) -> TriggerIncidentResponse:

    # ── Guardrail Layer 1: security (injection) check ──────────────────────
    try:
        SecurityGuard.check_and_sanitize(body.description, max_length=2000)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # ── Guardrail Layer 2: relevance check (not a search/question) ────────
    try:
        RelevanceGuard.validate(body.description)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    # Resolve timestamp
    triggered_at = body.triggered_at or datetime.now(timezone.utc)

    # Check for duplicate
    if store.get(body.alert_id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Incident '{body.alert_id}' already exists. Use GET to check its status.",
        )

    # Create record in store
    record = store.create(
        incident_id  = body.alert_id,
        service      = body.service,
        severity     = body.severity,
        triggered_at = triggered_at,
    )

    # Build the Alert model for the graph
    alert = Alert(
        alert_id     = body.alert_id,
        service      = body.service,
        severity     = Severity(body.severity.value),
        description  = body.description,
        triggered_at = triggered_at,
        environment  = body.environment,
        metadata     = body.metadata,
    )

    # Fire the graph in a background thread — does NOT block this handler
    start_incident(graph=graph, store=store, record=record, alert=alert)

    log.info(f"[api] Triggered incident {body.alert_id} for service '{body.service}'")

    return TriggerIncidentResponse(
        incident_id = body.alert_id,
        status      = IncidentStatusEnum.PENDING,
        message     = "Incident investigation started. Poll GET /incidents/{incident_id} for status.",
    )


# ── GET /incidents ────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=list[IncidentSummary],
    summary="List all incidents",
)
async def list_incidents(store: StoreDep) -> list[IncidentSummary]:
    return [
        IncidentSummary(
            incident_id  = r.incident_id,
            service      = r.service,
            severity     = r.severity,
            status       = r.status,
            triggered_at = r.triggered_at,
            completed_at = r.completed_at,
        )
        for r in store.all()
    ]


# ── GET /incidents/{incident_id} ──────────────────────────────────────────────

@router.get(
    "/{incident_id}",
    response_model=IncidentSummary,
    summary="Get incident status",
)
async def get_incident_status(
    incident_id: str,
    store:       StoreDep,
) -> IncidentSummary:

    try:
        r = store.get_or_raise(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    return IncidentSummary(
        incident_id  = r.incident_id,
        service      = r.service,
        severity     = r.severity,
        status       = r.status,
        triggered_at = r.triggered_at,
        completed_at = r.completed_at,
    )


# ── GET /incidents/{incident_id}/report ───────────────────────────────────────

@router.get(
    "/{incident_id}/report",
    response_model=IncidentReportResponse,
    summary="Get the full incident report (available once status is 'completed')",
)
async def get_incident_report(
    incident_id: str,
    store:       StoreDep,
) -> IncidentReportResponse:

    try:
        r = store.get_or_raise(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    if r.status not in (IncidentStatusEnum.COMPLETED, IncidentStatusEnum.WAITING):
        raise HTTPException(
            status_code=status.HTTP_425_TOO_EARLY,
            detail=f"Report not ready. Current status: '{r.status}'. Poll again later.",
        )

    state = r.final_state or {}

    # Helper: works whether the value is a Pydantic model or a plain dict
    # (state reloaded from SQLite is deserialized as plain dicts via json.loads)
    def _get(obj, key, default=None):
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    # Extract root cause if available
    root_cause_resp = None
    rc = state.get("root_cause")
    if rc:
        root_cause_resp = RootCauseResponse(
            hypothesis           = _get(rc, "hypothesis", ""),
            confidence_score     = _get(rc, "confidence_score", 0.0),
            confidence_reasoning = _get(rc, "confidence_reasoning", ""),
            recommended_action   = _get(rc, "recommended_action", ""),
            supporting_evidence  = _get(rc, "supporting_evidence", []),
        )

    # Extract report metadata if available
    report = state.get("incident_report")

    log_a    = state.get("log_analysis")
    metric_a = state.get("metric_analysis")
    deploy_a = state.get("deployment_analysis")

    return IncidentReportResponse(
        report_id           = _get(report, "report_id", "N/A"),
        incident_id         = r.incident_id,
        service             = r.service,
        severity            = r.severity,
        triggered_at        = r.triggered_at,
        generated_at        = _get(report, "generated_at") or r.completed_at or r.triggered_at,
        status              = r.status,
        root_cause          = root_cause_resp,
        human_input         = state.get("human_input"),
        log_summary         = _get(log_a, "summary"),
        metric_summary      = _get(metric_a, "summary"),
        deployment_summary  = _get(deploy_a, "summary"),
    )


# ── POST /incidents/{incident_id}/resume ──────────────────────────────────────

@router.post(
    "/{incident_id}/resume",
    response_model=HITLResumeResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resume a HITL-paused incident with engineer input",
    description=(
        "Called by an engineer (or the dashboard UI) when an incident is in "
        "'waiting' state. Injects the engineer's context and resumes the graph."
    ),
)
async def resume_incident_hitl(
    incident_id: str,
    body:        HITLResumeRequest,
    graph:       GraphDep,
    store:       StoreDep,
) -> HITLResumeResponse:

    try:
        r = store.get_or_raise(incident_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Incident '{incident_id}' not found")

    if r.status != IncidentStatusEnum.WAITING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Incident is in '{r.status}' state, not 'waiting'. Cannot resume.",
        )

    resume_incident(
        graph        = graph,
        store        = store,
        record       = r,
        human_input  = body.human_input,
    )

    log.info(f"[api] Resumed HITL for incident {incident_id}")

    return HITLResumeResponse(
        incident_id = incident_id,
        status      = IncidentStatusEnum.RUNNING,
        message     = "Graph resumed with your input. Poll GET /incidents/{incident_id} for completion.",
    )
