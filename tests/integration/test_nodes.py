import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from graph.state import IncidentState
from agents.models import Alert, Severity
from datetime import datetime, timezone
from agents.nodes import log_analysis_node, metric_analysis_node, deployment_analysis_node

test_state = IncidentState(
    alert=Alert(
        alert_id="INC-001",
        service="payment-service",
        severity=Severity.CRITICAL,
        description="High error rate on checkout",
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

print("--- Testing Log Analysis Node ---")
log_result = log_analysis_node(test_state)
assert log_result['log_analysis'] is not None
assert log_result['log_analysis'].summary != ""
print(f"Log Output: {log_result['log_analysis'].summary[:100]}...\n")

print("--- Testing Metric Analysis Node ---")
metric_result = metric_analysis_node(test_state)
assert metric_result['metric_analysis'] is not None
assert metric_result['metric_analysis'].summary != ""
print(f"Metric Output: {metric_result['metric_analysis'].summary[:100]}...\n")

print("--- Testing Deployment Analysis Node ---")
deploy_result = deployment_analysis_node(test_state)
assert deploy_result['deployment_analysis'] is not None
assert deploy_result['deployment_analysis'].summary != ""
print(f"Deployment Output: {deploy_result['deployment_analysis'].summary[:100]}...\n")

print("ALL NODES PASSED!")
