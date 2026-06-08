"""
agents/models.py — All Pydantic models for the AIRP agent.

These are the "contracts" between every node in the graph.
Every LLM output, tool output, and state object is typed here.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enumerations ──────────────────────────────────────────────────────────────

class Severity(str, Enum):
    """Standardised severity levels mirroring PagerDuty / OpsGenie."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class IncidentStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"
    NEEDS_HUMAN = "needs_human"


# ── Raw evidence models (inputs to analysis nodes) ────────────────────────────

class Alert(BaseModel):
    """The triggering alert that starts an incident investigation."""
    alert_id: str = Field(..., description="Unique alert identifier")
    service: str = Field(..., description="Affected service name, e.g. 'payments-api'")
    severity: Severity
    description: str = Field(..., description="Human-readable alert description")
    triggered_at: datetime
    environment: str = Field(default="production")
    difficulty: str = Field(default="unknown", description="Difficulty level of the incident")
    metadata: dict[str, Any] = Field(default_factory=dict)


class LogEntry(BaseModel):
    """A single structured log line from the synthetic log store."""
    timestamp: datetime
    level: str                   # ERROR, WARN, INFO, DEBUG
    service: str
    message: str
    trace_id: str | None = None
    error_code: str | None = None
    stack_trace: str | None = None


class MetricPoint(BaseModel):
    """A single time-series metric sample."""
    timestamp: datetime
    metric_name: str             # e.g. "error_rate", "p99_latency_ms"
    value: float
    unit: str = ""               # "percent", "ms", "rps", etc.
    service: str


class DeploymentRecord(BaseModel):
    """A record of a deployment event from the deployment history store."""
    deploy_id: str
    service: str
    version: str
    deployed_at: datetime
    deployed_by: str
    status: str                  # "success", "failed", "rolled_back"
    changes_summary: str         # Brief description of what changed
    rollback_available: bool = True


# ── LLM-structured outputs (what each analysis node returns) ──────────────────

class LogAnalysis(BaseModel):
    """Structured output from the Log Analysis Node."""
    service: str
    error_patterns: list[str] = Field(
        description="Distinct error patterns identified in logs"
    )
    anomaly_window: str = Field(
        description="Time window where anomalies were concentrated, e.g. '14:02–14:07 UTC'"
    )
    key_error_codes: list[str] = Field(default_factory=list)
    summary: str = Field(description="1-3 sentence natural language summary")
    extraction_failed: bool = Field(
        default=False,
        description="True when the LLM failed to extract data. Signals that error_patterns here are NOT real evidence."
    )


class MetricAnalysis(BaseModel):
    """Structured output from the Metric Analysis Node."""
    service: str
    degraded_metrics: list[str] = Field(
        description="Names of metrics that showed abnormal values"
    )
    peak_value: float | None = None
    baseline_value: float | None = None
    anomaly_start: datetime | None = None
    summary: str
    extraction_failed: bool = Field(
        default=False,
        description="True when the LLM failed to extract data. Signals that degraded_metrics here are NOT real evidence."
    )


class DeploymentAnalysis(BaseModel):
    """Structured output from the Deployment Analysis Node."""
    service: str
    recent_deployments: list[DeploymentRecord]
    suspicious_deploy: DeploymentRecord | None = Field(
        default=None,
        description="The deployment most likely to have caused the incident",
    )
    time_correlation: str = Field(
        description="Explanation of temporal relationship between deploy and incident"
    )
    summary: str
    extraction_failed: bool = Field(
        default=False,
        description="True when the LLM failed to extract data. Signals that suspicious_deploy here is NOT real evidence."
    )


# ── Correlation output ────────────────────────────────────────────────────────

class RootCauseHypothesis(BaseModel):
    """
    The synthesised root cause produced by the Correlation Node.
    This is the most important model in the system.
    """
    hypothesis: str = Field(
        description="One clear sentence stating the root cause"
    )
    core_cause: str = Field(
        description="The fundamental high-level core cause (e.g., 'Database lock', 'Network partition')"
    )
    technical_details: str = Field(
        description="Specific technical details including service names, versions, and exact error mechanisms"
    )
    chain_of_events: str = Field(
        description="Step-by-step explanation of how the cause logically led to the observed symptoms"
    )
    supporting_evidence: list[str] = Field(
        description="Bullet-point evidence from logs, metrics, and deployments"
    )
    confidence_score: float = Field(
        description="0.0–1.0. Drives the conditional edge decision.",
        ge=0.0,
        le=1.0,
    )
    confidence_reasoning: str = Field(
        description="Why this confidence score was assigned"
    )
    recommended_action: str = Field(
        description="Immediate mitigation step, e.g. 'Roll back deploy d-4821'"
    )


# ── Incident Report ───────────────────────────────────────────────────────────

class IncidentReport(BaseModel):
    """Final artifact generated by the Report Generation Node."""
    report_id: str
    alert: Alert
    log_analysis: LogAnalysis
    metric_analysis: MetricAnalysis
    deployment_analysis: DeploymentAnalysis
    root_cause: RootCauseHypothesis
    human_input: str | None = Field(
        default=None,
        description="Additional context provided by engineer during HITL",
    )
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: IncidentStatus = IncidentStatus.RESOLVED


