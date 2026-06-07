import pytest
from pydantic import ValidationError
from agents.models import LogAnalysis, MetricAnalysis, RootCauseHypothesis

def test_log_analysis_validation():
    # Valid
    log_a = LogAnalysis(
        service="test",
        earliest_error_time="2024-01-01T12:00:00Z",
        error_codes_seen=["HTTP_500"],
        error_patterns=[],
        anomaly_window="5m",
        summary="Test",
        stack_traces=["Trace"]
    )
    assert log_a.service == "test"
    
    # Invalid (missing required fields like summary)
    with pytest.raises(ValidationError):
        LogAnalysis(service="test", earliest_error_time="2024-01-01T12:00:00Z")

def test_metric_analysis_validation():
    metric_a = MetricAnalysis(
        service="test",
        degraded_metrics=["cpu_percent"],
        summary="CPU high"
    )
    assert metric_a.service == "test"

def test_root_cause_validation():
    # Confidence score must be between 0 and 1
    with pytest.raises(ValidationError):
        RootCauseHypothesis(
            confidence_reasoning="Test",
            hypothesis="Test",
            confidence_score=1.5,
            supporting_evidence=["Test1"],
            contradicting_evidence=[],
            recommended_action="Test"
        )
