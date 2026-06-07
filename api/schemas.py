"""
api/schemas.py — FastAPI request/response schemas.

These are SEPARATE from agents/models.py on purpose.
  - agents/models.py  → contracts between LangGraph nodes (internal)
  - api/schemas.py    → contracts with API callers (external)

This separation means you can change the internal agent without
breaking the public API contract, and vice-versa.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
from agents.security import SecurityGuard


# ── Enums ─────────────────────────────────────────────────────────────────────

class IncidentStatusEnum(str, Enum):
    PENDING    = "pending"      # Just received, graph not yet started
    RUNNING    = "running"      # Graph is actively processing
    WAITING    = "waiting"      # Paused at HITL interrupt, awaiting human
    COMPLETED  = "completed"    # Graph finished successfully
    FAILED     = "failed"       # Unrecoverable error

class SeverityLevel(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# ── Inbound Request Schemas ───────────────────────────────────────────────────

class TriggerIncidentRequest(BaseModel):
    """
    POST /incidents/trigger

    Payload shape that an external alerting tool (PagerDuty, Datadog, OpsGenie)
    would send when a new alert fires.
    """
    alert_id:     str = Field(...,  description="Unique alert/incident ID from the monitoring tool")
    service:      str = Field(...,  description="Affected service name, e.g. 'payments-api'")
    severity:     SeverityLevel = Field(SeverityLevel.HIGH, description="Incident severity")
    description:  str = Field(...,  description="Human-readable description of what went wrong", max_length=500)
    
    @field_validator("description")
    @classmethod
    def sanitize_description(cls, v: str) -> str:
        return SecurityGuard.check_and_sanitize(v, max_length=500)
    triggered_at: Optional[datetime] = Field(
        default=None,
        description="ISO-8601 timestamp. Defaults to now() if omitted."
    )
    environment:  str = Field(default="production")
    metadata:     dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary key-value pairs from the alerting tool"
    )


class HITLResumeRequest(BaseModel):
    """
    POST /incidents/{incident_id}/resume

    Payload an engineer submits via the dashboard (or curl) to provide
    additional context and resume the paused graph.
    """
    human_input: str = Field(
        ...,
        description="Engineer's diagnosis or additional context to inject into the graph",
        min_length=10,
        max_length=1000
    )

    @field_validator("human_input")
    @classmethod
    def sanitize_human_input(cls, v: str) -> str:
        return SecurityGuard.check_and_sanitize(v, max_length=1000)


# ── Outbound Response Schemas ─────────────────────────────────────────────────

class IncidentSummary(BaseModel):
    """Lightweight status object — used in list endpoints and polling."""
    incident_id:  str
    service:      str
    severity:     str
    status:       IncidentStatusEnum
    triggered_at: datetime
    completed_at: Optional[datetime] = None


class RootCauseResponse(BaseModel):
    """Subset of the full RootCauseHypothesis surfaced in the API."""
    hypothesis:          str
    confidence_score:    float
    confidence_reasoning: str
    recommended_action:  str
    supporting_evidence: list[str]


class IncidentReportResponse(BaseModel):
    """
    Full incident report returned by GET /incidents/{incident_id}/report
    """
    report_id:    str
    incident_id:  str
    service:      str
    severity:     str
    triggered_at: datetime
    generated_at: datetime
    status:       IncidentStatusEnum

    root_cause:   Optional[RootCauseResponse] = None
    human_input:  Optional[str]               = None

    log_summary:        Optional[str] = None
    metric_summary:     Optional[str] = None
    deployment_summary: Optional[str] = None


class TriggerIncidentResponse(BaseModel):
    """Response immediately returned when POST /incidents/trigger is called."""
    incident_id: str
    status:      IncidentStatusEnum
    message:     str


class HITLResumeResponse(BaseModel):
    """Response after POST /incidents/{incident_id}/resume is called."""
    incident_id: str
    status:      IncidentStatusEnum
    message:     str


class ErrorResponse(BaseModel):
    """Standard error envelope."""
    error:   str
    detail:  Optional[str] = None
    code:    int            = 500
