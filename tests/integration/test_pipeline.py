import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.state import IncidentState
from agents.models import Alert, Severity
from datetime import datetime, timezone
from agents.nodes import (
    log_analysis_node, metric_analysis_node, deployment_analysis_node,
    correlation_node, route_after_correlation, report_generation_node
)

# Build initial state
state = IncidentState(
    alert=Alert(
        alert_id="INC-001",
        service="payment-service",
        severity=Severity.CRITICAL,
        description="High error rate on payment-service",
        triggered_at=datetime(2024, 1, 15, 2, 26, 0, tzinfo=timezone.utc)
    ),
    log_analysis=None,
    metric_analysis=None,
    deployment_analysis=None,
    past_similar_incidents=[],
    root_cause=None,
    needs_human_input=False,
    human_input=None,
    hitl_iteration=0,
    incident_report=None
)

# Run each analysis node
print("=== PHASE 1: PARALLEL ANALYSIS ===")
state.update(log_analysis_node(state))  # type: ignore[typeddict-item]
state.update(metric_analysis_node(state))  # type: ignore[typeddict-item]
state.update(deployment_analysis_node(state))  # type: ignore[typeddict-item]

print("\n=== PHASE 2: CORRELATION ===")
state.update(correlation_node(state))  # type: ignore[typeddict-item]
assert state["root_cause"] is not None, "Correlation node must produce a hypothesis"
assert 0.0 <= state["root_cause"].confidence_score <= 1.0, "Confidence must be in [0, 1]"
print(f"Hypothesis: {state['root_cause'].hypothesis}")
print(f"Confidence: {state['root_cause'].confidence_score:.2f}")
print(f"HITL needed: {state['needs_human_input']}")

print("\n=== PHASE 3: ROUTING ===")
route = route_after_correlation(state)
assert route in ("hitl_node", "report_generation_node"), f"Router returned invalid node: {route}"
print(f"Router decision: {route}")


if not state["needs_human_input"]:
    print("\n=== PHASE 4: REPORT ===")
    state.update(report_generation_node(state))  # type: ignore[typeddict-item]
    assert state["incident_report"] is not None
    print(f"Report ID: {state['incident_report'].report_id}")

print("\nALL PIPELINE TESTS PASSED!")
