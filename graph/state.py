from typing import TypedDict, Optional
from agents.models import (
    Alert, LogAnalysis, MetricAnalysis, DeploymentAnalysis, 
    RootCauseHypothesis, IncidentReport
)

class IncidentState(TypedDict):
    """
    State dictionary that flows through all nodes in the graph.
    """
    alert: Alert
    
    # ── Analysis Phase ────────────────────────────────────────────────────────
    log_analysis: Optional[LogAnalysis]
    metric_analysis: Optional[MetricAnalysis]
    deployment_analysis: Optional[DeploymentAnalysis]
    
    # ── Memory Phase ──────────────────────────────────────────────────────────
    past_similar_incidents: Optional[list[str]]
    
    # ── Correlation Phase ─────────────────────────────────────────────────────
    root_cause: Optional[RootCauseHypothesis]
    needs_human_input: bool
    human_input: Optional[str]
    hitl_iteration: int  # Prevent infinite loops if human input fails to increase confidence
    
    # ── Final ─────────────────────────────────────────────────────────────────
    incident_report: Optional[IncidentReport]
