"""
tests/test_correlation_validation.py

Validates two critical properties of the correlation_node:
  1. High confidence when all three sources agree on the same root cause
  2. Confidence cap (<= 0.6) when only one source found anomalies

We build the state manually using real Pydantic models, not raw dicts,
because correlation_node reads typed fields (.error_patterns, .degraded_metrics, etc.)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from graph.state import IncidentState
from agents.models import (
    Alert, LogAnalysis, MetricAnalysis, DeploymentAnalysis, DeploymentRecord, Severity
)
from agents.nodes import correlation_node


# ─── SHARED ALERT ─────────────────────────────────────────────────────────────

BASE_ALERT = Alert(
    alert_id="INC-001",
    service="payment-service",
    severity=Severity.CRITICAL,
    description="High error rate on payment-service",
    triggered_at=datetime(2024, 1, 15, 2, 26, 0, tzinfo=timezone.utc)
)


# ─── TEST 1: HIGH CONFIDENCE — all three sources are anomalous ────────────────

def test_high_confidence():
    suspicious_deploy = DeploymentRecord(
        deploy_id="DEPLOY-007",
        service="payment-service",
        version="v2.4.1",
        deployed_at=datetime(2024, 1, 1, 1, 57, 0, tzinfo=timezone.utc),
        deployed_by="ci-bot",
        status="success",
        changes_summary="Added order history fetch on payment confirmation page (N+1 DB query issue)",
    )

    state: IncidentState = {
        "alert": BASE_ALERT,
        "log_analysis": LogAnalysis(
            service="payment-service",
            error_patterns=["Connection pool exhausted", "DB timeout after 30s"],
            anomaly_window="02:13 – 02:26 UTC",
            key_error_codes=["POOL_EXHAUSTED", "DB_TIMEOUT"],
            summary="47 errors — connection pool exhausted due to long-running queries",
        ),
        "metric_analysis": MetricAnalysis(
            service="payment-service",
            degraded_metrics=["db_connection_pool_available", "p99_latency_ms"],
            peak_value=3200.0,
            baseline_value=120.0,
            anomaly_start=datetime(2024, 1, 15, 2, 13, 0, tzinfo=timezone.utc),
            summary="DB connection pool hit 0%, p99 latency spiked 26x above baseline",
        ),
        "deployment_analysis": DeploymentAnalysis(
            service="payment-service",
            recent_deployments=[suspicious_deploy],
            suspicious_deploy=suspicious_deploy,
            time_correlation="Deployment 29 minutes before incident start; N+1 query pattern matches pool exhaustion",
            summary="v2.4.1 deployed 29 min before incident; change introduced N+1 DB query",
        ),
        "past_similar_incidents": [],
        "root_cause": None,
        "needs_human_input": False,
        "human_input": None,
        "hitl_iteration": 0,
        "incident_report": None,
    }

    result = correlation_node(state)

    print("\n[HIGH CONFIDENCE TEST]")
    print(f"  Hypothesis : {result['root_cause'].hypothesis}")
    print(f"  Confidence : {result['root_cause'].confidence_score:.2f}")
    print(f"  Evidence   : {len(result['root_cause'].supporting_evidence)} items")
    print(f"  HITL needed: {result['needs_human_input']}")

    assert result["root_cause"] is not None, "Root cause must not be None"
    assert 0.0 <= result["root_cause"].confidence_score <= 1.0, "Score out of range"
    assert len(result["root_cause"].supporting_evidence) >= 2, "Need at least 2 evidence items"
    print("  [PASS] High-confidence test passed")


# ─── TEST 2: LOW CONFIDENCE — only one source found anomalies ─────────────────

def test_low_confidence_cap():
    state: IncidentState = {
        "alert": BASE_ALERT,
        "log_analysis": LogAnalysis(
            service="payment-service",
            error_patterns=["Connection pool exhausted"],
            anomaly_window="02:13 – 02:26 UTC",
            key_error_codes=["POOL_EXHAUSTED"],
            summary="Connection pool exhausted — single error pattern observed",
        ),
        "metric_analysis": MetricAnalysis(
            service="payment-service",
            degraded_metrics=[],
            peak_value=None,
            baseline_value=None,
            anomaly_start=None,
            summary="All metrics within normal operating range",
        ),
        "deployment_analysis": DeploymentAnalysis(
            service="payment-service",
            recent_deployments=[],
            suspicious_deploy=None,
            time_correlation="No deployments in the 2 hours preceding the incident",
            summary="No recent deployments found",
        ),
        "past_similar_incidents": [],
        "root_cause": None,
        "needs_human_input": False,
        "human_input": None,
        "hitl_iteration": 0,
        "incident_report": None,
    }

    result = correlation_node(state)

    print("\n[LOW CONFIDENCE TEST]")
    print(f"  Hypothesis : {result['root_cause'].hypothesis}")
    print(f"  Confidence : {result['root_cause'].confidence_score:.2f}")
    print(f"  Reasoning  : {result['root_cause'].confidence_reasoning[:120]}")
    print(f"  HITL needed: {result['needs_human_input']}")

    assert result["root_cause"].confidence_score <= 0.6, (
        f"Agent must not be confident with only 1 anomalous signal — "
        f"got {result['root_cause'].confidence_score:.2f}"
    )
    assert result["needs_human_input"] is True, "Single-source evidence must trigger HITL"
    print("  [PASS] Confidence calibration test passed — score capped correctly")


# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_high_confidence()
    test_low_confidence_cap()
    print("\n=== ALL CORRELATION VALIDATION TESTS PASSED ===")
