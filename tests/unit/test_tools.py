import pytest
from tools.log_tools import query_logs, LogQueryInput
from tools.metric_tools import query_metrics, MetricQueryInput
from tools.deployment_tools import query_deployments, DeploymentQueryInput

# --- Log Tools ---

def test_valid_incident_returns_logs():
    result = query_logs(LogQueryInput(incident_id="INC-001"))
    assert result.incident_id == "INC-001"
    assert len(result.logs) > 0
    assert result.service is not None

def test_invalid_incident_raises_error():
    with pytest.raises(ValueError, match="not found in logs.json"):
        query_logs(LogQueryInput(incident_id="FAKE-999"))

def test_level_filter_works():
    result = query_logs(LogQueryInput(
        incident_id="INC-001",
        level_filter=["ERROR"]
    ))
    for log in result.logs:
        assert log.level == "ERROR"

def test_limit_is_respected():
    result = query_logs(LogQueryInput(incident_id="INC-001", limit=3))
    assert len(result.logs) <= 3

# --- Metric Tools ---

def test_metrics_query_valid_incident():
    result = query_metrics(MetricQueryInput(incident_id="INC-001"))
    assert result.incident_id == "INC-001"
    assert len(result.anomalous_metrics) > 0  # INC-001 should have some high CPU/memory

def test_metrics_query_invalid():
    with pytest.raises(ValueError, match="not found in logs.json"):
        query_metrics(MetricQueryInput(incident_id="FAKE-999"))

# --- Deployment Tools ---

def test_deployments_query_valid_incident():
    result = query_deployments(DeploymentQueryInput(incident_id="INC-001"))
    assert result.incident_id == "INC-001"

def test_deployments_query_invalid():
    with pytest.raises(ValueError, match="not found in logs.json"):
        query_deployments(DeploymentQueryInput(incident_id="FAKE-999"))
